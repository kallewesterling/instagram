"""Instagram module.

Creates datasets and easy-to-use analysis tools for Instagram data.

Basic use:
- InstagramPost(shortcode, expand=True)
- InstagramUser(shortcode, expand=True)
- InstagramLocation(shortcode, expand=True)
"""

__version__ = '2019-04-29'
__author__ = 'Kalle Westerling'


# STANDARD SETTINGS

cfg = {
	'level_reporting': 10,
	'downloads_wait_min': 1,
	'downloads_wait_max': 3,
	'cache_folder': '/Users/kallewesterling/Dropbox/dev/instagram-hashtags/instagramanalysis/__cache__/',

	'hashtags_datasets': '/Users/kallewesterling/Dropbox/datasets/instagram-hashtags',
	'users_datasets': '/Users/kallewesterling/Dropbox/datasets/instagram-users',

	'max_attempts': 5,

	'TWITTER_datasets': '/Users/kallewesterling/Dropbox/datasets/twitter-boylesque',
	'TWITTER_consumer_key': 'PAKAd5cDFEvhlaMClRetKuX52',
	'TWITTER_consumer_secret': 'Iva6kXk2bibYNMvzuKSuYnpTr4UZ9ri7hYuc3TELI2C3RQSfy4',
	'TWITTER_access_token': '16474279-FHQlTOkLnPW3xuNFMXd6ZrRkzzvojqtaxW0bJGFvn',
	'TWITTER_access_token_secret': 'G5Ktm7XQvHXN7EynDLbdV1AtPTbY8CG29peFlj5R97gjn',
}




# IMPORTS

import re
import requests
import json
import os
import time
import string
import sys
import glob
import shutil
import collections
import random

from pathlib import Path
from pprint import pprint
from operator import itemgetter
from datetime import datetime as dt
from datetime import timezone
from random import randrange


import progressbar
import tweepy

import pandas as pd

from bs4 import BeautifulSoup
from nltk.corpus import stopwords
from selenium import webdriver


# Fix paths in config

cfg['cache_folder'] = Path(cfg['cache_folder'])
cfg['hashtags_datasets'] = Path(cfg['hashtags_datasets'])
cfg['users_datasets'] = Path(cfg['users_datasets'])
cfg['TWITTER_datasets'] = Path(cfg['TWITTER_datasets'])



# Logging

def _log(msg, level=0):
	""" Internal function for rerouting log messages.

	Levels:
	0: Debug
	10: Warning
	20: Severe Warning
	"""
	if level >= cfg['level_reporting']:
		print(msg)




class InstagramDataset(object):
	""" Creates a Dataset object based on a list of hashtags.

	Keywords:
	hashtags -- a list of Instagram hashtags (default empty list)

	"""

	def __init__(self, hashtags=[], users=[], shortcodes=[], limited=False, download_all_nodes=False, exclude_users=[]):
		# Raise init errors
		if len(hashtags) == 0 and len(shortcodes) == 0 and len(users) == 0:
			raise SyntaxError("Error: You have to provide a list of hashtags (with at least one hashtag) or a list of shortcodes (with at least one shortcode).")
		elif (len(hashtags) > 0 and len(shortcodes) > 0) or (len(hashtags) > 0 and len(users) > 0) or (len(users) > 0 and len(shortcodes) > 0):
			raise SyntaxError("Error: You can only provide a list of hashtags OR a list of shortcodes OR a list of users.")
		
		# Fix hashtags passed as string = make it into a one-element list
		# if isinstance(hashtags, str): hashtags = [hashtags]

		# Define global variables for Dataset
		self.hashtags = hashtags
		self._users = users
		self.limited = limited
		self.exclude_users = exclude_users
		self._all_hashtags = None
		self._all_mentions = None
		self._all_tagged = None
		self._all_countries = None
		self._all_nodes = download_all_nodes

		# Get all shortcodes for Dataset
		if len(hashtags) > 0:
			self.shortcodes = get_shortcodes_from_hashtags(hashtags)
		elif len(users) > 0:
			self.shortcodes = get_shortcodes_from_users(self._users)
		elif len(shortcodes) > 0:
			self.shortcodes = shortcodes

		if not self.limited:
			# Set up external objects in Dataset
			self.captions = self.Captions()
			self.geo = self.Geo()
			self.network = self.Network()

		# Set up posts in Dataset
		self.posts = self._setup_posts()

	def __str__(self):
		if len(self.hashtags) > 0:
			return f"Instagram dataset {self.hashtags} consisting of {len(self.shortcodes)} posts."
		else:
			return f"Instagram dataset consisting of {len(self.shortcodes)} posts."

	def __getitem__(self, position):
		return self.posts[position]

	def __len__(self):
		return len(self.posts)

	def _setup_posts(self):
		_log(f"Loading list of posts based on hashtags {self.hashtags}...", 0)

		# Standard variables
		_r, users_counted = [], []
		i, self.no_captions, self.ads, self.sponsored_users, self.edited_captions, self.videos, self.sidecars, self.images, self.users_businesses, self.users_joined_recently, self.are_private, self.are_verified, self.have_locations = 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0

		# Start a progressbar
		bar = progressbar.ProgressBar(max_value=len(self.shortcodes)).start()

		for s in self.shortcodes:
			_break = False
			attempts = 1
			post = None
			
			if len(s) == 0:
				_log(f"Debug warning: Length 0 shortcode found in the dataset using hashtags {self.hashtags}.")
				continue
			
			while _break == False:
				try:
					post = InstagramPost(s, expand=True)
					_break = True
				except Exception as e:
					wait_for_download()
					attempts += 1
					_log(f"Debug warning: Download attempt failed. Attempt number {attempts} commences.")
					if attempts == cfg["max_attempts"]+1: _break = True
			
			if post is None: raise RuntimeError(f"Error downloading post {s}.")
			if not post.ok: continue # Make sure only posts that were found are in the dataset.. This is not always what one might want, however.

			if not post.user.username in self.exclude_users: _r.append(post)

			# Summarize post
			if post.caption is None or post.caption == "": self.no_captions += 1
			if post.is_ad: self.ads += 1
			if post.sponsored_users: self.sponsored_users += 1
			if post.caption_is_edited: self.edited_captions += 1
			if post.type == "GraphVideo": self.videos +=1
			if post.type == "GraphSidecar": self.sidecars +=1
			if post.type == "GraphImage": self.images +=1

			if post.user.username not in users_counted:
				# Summarize user
				if post.user.is_business_account: self.users_businesses += 1
				if post.user.is_joined_recently: self.users_joined_recently += 1
				if post.user.is_private: self.are_private += 1
				if post.user.is_verified: self.are_verified += 1

				# Make sure users are not counted twice
				users_counted.append(post.user.username)

			if not self.limited:
				# Captions updates
				self.captions.update(post)

			# Summarize location
			if post.location is not None:
				self.have_locations +=1
				if not self.limited: self.geo.update_coordinates(post.location)

			if not self.limited:
				# Create network
				self.network.update_edges(post)
				self.network.update_nodes(post, download=self._all_nodes)

			# Update progressbar
			i+=1
			bar.update(i)

		# Finish progressbar
		bar.finish()

		return(_r)

	def setup_network(self):
		self.network = self.Network()

		# Standards
		i = 0

		# Start a progressbar
		bar = progressbar.ProgressBar(max_value=len(self.posts)).start()

		for post in self.posts:
			self.network.update_edges(post)
			self.network.update_nodes(post, download=self._all_nodes)

			# Update progressbar
			i += 1
			bar.update(i)

		# Finish progressbar
		bar.finish()


	def get_all_tagged(self):
		if self._all_tagged == None:
			self._all_tagged = {}
			for post in self.posts:
				for t in post.tagged_users:
					if t['username'] not in self._all_tagged: self._all_tagged[t['username']] = 0
					self._all_tagged[t['username']] += 1
			self._all_tagged = sorted(self._all_tagged.items(), key=itemgetter(1), reverse=True)
		return(self._all_tagged)


	def get_all_mentions(self):
		if self._all_mentions == None:
			self._all_mentions = {}
			for post in self.posts:
				if post.caption:
					for h in get_mentions(post.caption, lower=True):
						if h not in self._all_mentions: self._all_mentions[h] = 0
						self._all_mentions[h] += 1
			self._all_mentions = sorted(self._all_mentions.items(), key=itemgetter(1), reverse=True)
		return(self._all_mentions)


	def get_all_hashtags(self):
		if self._all_hashtags == None:
			self._all_hashtags = {}
			for post in self.posts:
				if post.caption:
					for h in get_hashtags(post.caption, lower=True):
						if h not in self._all_hashtags: self._all_hashtags[h] = 0
						self._all_hashtags[h] += 1
			self._all_hashtags = sorted(self._all_hashtags.items(), key=itemgetter(1), reverse=True)
		return(self._all_hashtags)


	def get_all_countries(self, suppress_warning=False):
		errors = []
		if self._all_countries == None:
			self._all_countries = {}
			for post in self.posts:
				if post.location is not None:
					if post.location.country not in self._all_countries: self._all_countries[post.location.country] = 1
					else: self._all_countries[post.location.country] += 1
				else:
					errors.append(post.shortcode)
			if not suppress_warning: _log(f"Warning: {len(errors)} locations did not have locations assigned. {errors}", 10)
			self._all_countries = sorted(self._all_countries.items(), key=itemgetter(1), reverse=True)
		return(self._all_countries)

	@property
	def all_tagged(self):
		if self._all_tagged is not None: return(self._all_tagged)
		else:
			return(self.get_all_tagged())

	@property
	def all_hashtags(self):
		if self._all_hashtags is not None: return(self._all_hashtags)
		else:
			return(self.get_all_hashtags())

	@property
	def all_mentions(self):
		if self._all_mentions is not None: return(self._all_mentions)
		else:
			return(self.get_all_mentions())

	@property
	def users(self):
		return(self.explore(what="top-users"))

	@property
	def tagged(self):
		return(self.explore(what="top-tagged"))

	@property
	def mentioned(self):
		return(self.explore(what="top-mentioned"))

	@property
	def likes(self):
		return(self.explore(what="top-likes"))

	@property
	def summary(self):
		return(self.explore(what="summary"))

	def summary_to_file(self, path="./", prefix=None):
		_ = self.explore(what="summary", suppress_warning=True)
		filename = ""
		if prefix: filename = prefix
		filename += "summary.json"
		with open(path+filename, "w+") as f:
			json.dump(_, f)


	def reorganize(self, by="date", **kwargs):
		_log(f"Reorganizing dataset by {by}. Keyword arguments: {kwargs}", 0)
		# Test keyword arguments
		if by == "date" and "dateformat" in kwargs:
			# test keyword argument _dateformat_ to see whether it is a valid dateformat
			try:
				dt.now().strftime(kwargs['dateformat'])
			except ValueError:
				raise ValueError(f"Incorrect dateformat ({kwargs['dateformat']}): Must follow correct Python dateformat standards.") from None
		elif by == "date" and not "dateformat" in kwargs:
			kwargs = {"dateformat": ""}
			kwargs["dateformat"] = "%Y-%m"
		elif by == "captions" or by == "users" or by == "followers" or by == "coordinates" or by == "locations" or by == "is_business":
			pass #We can do things here...
		else:
			raise RuntimeError("Cannot understand how to reorganize dataset based on method {by}.") from None

		# Set up variables
		spliced = {}
		i = 0

		# Start a progressbar
		bar = progressbar.ProgressBar(max_value=len(self.posts)).start()

		for post in self.posts:
			# Update progressbar
			i+=1
			bar.update(i)

			if not post.ok: continue

			if by == "date":
				splicer = post.date.strftime(kwargs['dateformat'])
			elif by == "users":
				splicer = post.user.username
			elif by == "followers":
				splicer = post.user.followers
			elif by == "coordinates":
				if post.location is not None and post.location.lat is not None and post.location.lng is not None: splicer = f"{post.location.lat}, {post.location.lng}"
				else: splicer = "None"
			elif by == "locations":
				if post.location is not None and post.location.name is not None: splicer = f"{post.location.name}"
				else: splicer = "None"
			elif by == "is_business":
				splicer = post.user.is_business_account
			elif by == "captions":
				splicer = post.caption
				if "clean_caption" in kwargs and kwargs["clean_caption"]: splicer = clean_text(splicer, set_all=True)
			if splicer not in spliced: spliced[splicer] = {}
			if post.shortcode not in spliced[splicer]: spliced[splicer][post.shortcode] = post

		bar.finish()

		return(spliced)


	def search(self, terms=[], **kwargs):

		if isinstance(terms, str): terms = [terms]

		_r = {}
		for term in terms:
			_r[term] = []

		if "bufferzone" in kwargs: bufferzone = kwargs["bufferzone"]
		else: bufferzone = 30

		# Start a progressbar
		i=0
		bar = progressbar.ProgressBar(max_value=len(self.posts)).start()

		for post in self.posts:
			# Update progressbar
			i+=1
			bar.update(i)

			if not post.ok: continue
			if post.caption is None: continue

			search_text = post.caption

			if "search_comments" in kwargs and kwargs["search_comments"]: pass #add comments here..

			if "clean_search_text" in kwargs and kwargs["clean_search_text"]: search_text = clean_text(
				search_text,
				set_all=True)

			for term in terms:
				_ = re.finditer(term, search_text, flags=re.I | re.M | re.X)

				for match in _:
					if match.start() > bufferzone: start = match.start() - bufferzone
					else: start = 0
					end = match.end() + bufferzone
					text = search_text[start:end]
					_r[term].extend([post, text])

		bar.finish()

		return(_r)

	@property
	def calendar_df(self):
		return(pd.DataFrame([
			[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
			[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
			[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
			[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
			[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
			[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
			[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
			[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
			[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
			[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
			[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
			[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
			[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
			[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
			[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
			[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
			[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
			[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
			[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
			[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
			[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
			[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
			[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
			[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
			[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
			[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
			[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
			[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
			[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
			[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
			[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
			[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
		], columns=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]).astype(int))

	def posts_per_day(self, **kwargs):
		_posts, _dfs = {}, {}

		try: self._posts_per_day
		except: self._posts_per_day = None

		if self._posts_per_day is None:
			for date, posts in self.reorganize(by="date", dateformat="%Y-%m-%d").items():
				year, month, day = date.split("-")
				year, month, day = int(year), int(month), int(day)
				if year not in _posts: _posts[year] = {}
				if month not in _posts[year]: _posts[year][month] = {}
				if day not in _posts[year][month]: _posts[year][month][day] = 0
				_posts[year][month][day] += len(posts)

			df = pd.DataFrame.from_dict(_posts)
			for c in df.columns:
				year_df = self.calendar_df
				df2 = df[c].apply(pd.Series)
				df2 = df2.fillna(0).T.astype(int)
				year_df.update(df2)
				_dfs[c] = year_df.astype(int)

			self._posts_per_day = _dfs

		if "year" in kwargs:
			# Return only one year of the DataFrames
			try:
				pos = kwargs["year"]
				return(self._posts_per_day[pos])
			except KeyError: # The requested year did not exist
				return(None)
		else:
			# Return all the DataFrames
			return(self._posts_per_day)


	def posts_per_month(self, **kwargs): # todo: redo as the posts_per_day above so we don't have to loop over dataset.reorganize every time we run the script
		_posts, _dfs = {}, {}

		for date, posts in self.reorganize(by="date", dateformat="%Y-%m").items():
			year, month = date.split("-")
			year, month = int(year), int(month)
			if year not in _posts: _posts[year] = {}
			if month not in _posts[year]: _posts[year][month] = 0
			_posts[year][month] += len(posts)

		df = pd.DataFrame.from_dict(_posts).T.fillna(0).astype(int).sort_index()
		_all = df.T

		if 'year' in kwargs:
			try:
				return(pd.DataFrame(df.loc[kwargs['year']]))
			except KeyError:
				return(None)
		else:
			return(_all)



	def find_user(self, username=None):
		if not username: raise SyntaxError("You must provide a username to search for.")
		_results = []
		for post in self.posts:
			mentions = get_mentions(post.caption)
			if username in mentions: _results.append((post.shortcode, "mention"))
			for t in post.tagged_users:
				if username in t['username']: _results.append((post.shortcode, "tagged"))
		return(_results)
		
	# Specific version of explore_dataset for these purposes

	def explore(self, what="top-users", filter_value=0, suppress_warning=False):
		if not isinstance(filter_value, int) or filter_value < 0: raise SyntaxError("filter_value must be a positive int.")

		if (what == "top-users" or
			what == "top-tagged" or
			what == "top-mentioned" or
			what == "top-likes"):

			users_in_dataset = {}

			for post in self.posts:

				if not post.ok: continue

				if what == "top-users":
					# top-users creates a list of all the usernames who have posted within the hashtag and a count value for each username
					if post.user.ok:
						if post.user.username not in users_in_dataset: users_in_dataset[post.user.username] = 1
						else: users_in_dataset[post.user.username] += 1

				elif what == "top-tagged":
					# top-tagged creates a list of all the usernames who have been tagged in a hashtag
					if post.tagged_users is not None and len(post.tagged_users) > 0:
						for t in post.tagged_users:
							if t['username'] not in users_in_dataset: users_in_dataset[t['username']] = 1
							else: users_in_dataset[t['username']] += 1

				elif what == "top-mentioned":
					# top-mentioned creates a list of all the usernames who have been mentioned in a hashtag
					if post.caption is not None and len(get_mentions(post.caption)) > 0:
						for m in get_mentions(post.caption):
							m = m.lower()
							if m not in users_in_dataset: users_in_dataset[m] = 1
							else: users_in_dataset[m] += 1

				elif what == "top-likes":
					# top-likes creates a list of the amount of likes each post have received in a hashtag
					if post.num_likes not in users_in_dataset: users_in_dataset[post.num_likes] = 1
					else: users_in_dataset[post.num_likes] += 1

			users_in_dataset = sorted(users_in_dataset.items(), key=itemgetter(1), reverse=True)

			return(users_in_dataset)

		elif what == "summary":
			return_value = {
				'num_shortcodes': len(self.shortcodes),
				'num_posts': len(self.posts),
				'caption_none': int(self.no_captions),
				'caption_edited': int(self.edited_captions),
				'num_ads': int(self.ads),
				'sponsored_users': int(self.sponsored_users),
				'type_videos': int(self.videos),
				'type_sidecars': int(self.sidecars),
				'type_images': int(self.images),
				'users_in_dataset': len(self.users),
				'users_businesses': int(self.users_businesses),
				'users_joined_recently': int(self.users_joined_recently),
				'users_private': int(self.are_private),
				'users_verified': int(self.are_verified),
				'num_posts_with_location': self.have_locations,
			}
			if not self.limited:
				return_value['locations'] = self.geo.coordinates_sorted
				return_value['potential_duplicate_captions'] = len(self.captions.potential_duplicates)
				return_value['20_longest_words'] = self.captions.longest_words(num=20)
				if self.have_locations > 0 and len(self.geo) > 0: return_value['num_posts_with_location_per_location'] = self.have_locations / len(self.geo)
				return_value['all_countries'] = self.get_all_countries(suppress_warning=suppress_warning)
				return_value['20_top_hashtags'] = self.all_hashtags[:20]
				return_value['20_top_tagged'] = self.all_tagged[:20]
				return_value['20_top_mentioned'] = self.all_mentions[:20]

			return(return_value)


	def to_pandas_csv(self, folder='./', filename="", includes={'caption', 'type', 'is_ad'}):
		for posts in post:
			print(post.include[0]) #TODO


	class Captions(object):
		def __init__(self):
			self.captured = []
			self.captions = {}
			self.captions_data = {}
			self._word_counts = {}
			self.all_emojis = {}

		def __len__(self):
			return(len(self.captions))

		def __str__(self):
			return f"Collection of Instagram captions consisting of {len(self.captions)} captions."

		def update(self, post): # post = InstagramPost object here
			caption = post.caption
			shortcode = post.shortcode

			if shortcode not in self.captured: #make sure we haven't captured it already
				self.captured.append(shortcode)

				if caption is not None:

					# Capture emojis
					for character in caption:
						try:
							character.encode("ascii")
						except UnicodeEncodeError:
							if character not in self.all_emojis: self.all_emojis[character] = 1
							else: self.all_emojis[character] += 1

					# Now clean text
					caption = clean_text(
							caption,
							expand_contractions=True,
							lower=True,
							no_at=True,
							no_digits=False,
							no_hash=True,
							no_links=True,
							no_punc=True,
							strip_emoji=True,
							strip_spaces=True) # Clean the caption but keep digits as they may differ from post to post

					if caption != "":
						if caption not in self.captions: self.captions[caption] = 0
						self.captions[caption] += 1

						if caption not in self.captions_data: self.captions_data[caption] = []
						if shortcode not in self.captions_data[caption]: self.captions_data[caption].append(shortcode)
			else:
				_log(f"{shortcode} already processed.", 0)


		def words(self, stop_words = []):
			if len(self._word_counts) <= 0:
				all_words = self.captions_as_text(all=True, clean=True).split(" ")
				for word in all_words:
					if word in stop_words: continue
					if word not in self._word_counts: self._word_counts[word] = 0
					self._word_counts[word] += 1
				self._word_counts = sorted(self._word_counts.items(), key=itemgetter(1), reverse=True)
			return(self._word_counts)

		@property
		def word_counts(self):
			if len(self._word_counts) == 0:
				self.words()
			return(self._word_counts)

		@property
		def emojis(self):
			return(sorted(self.all_emojis.items(), key=itemgetter(1), reverse=True))

		@property
		def unique(self):
			return(len(self.captions))

		@property
		def not_unique(self):
			return(sum(self.captions.values())-self.unique)

		@property
		def potential_duplicates(self):
			duplicates = {}
			for caption, count in self.captions.items():
				if count > 1:
					if caption not in duplicates: duplicates[caption] = []
					duplicates[caption].extend(self.captions_data[caption])
			return(duplicates)

		def to_text(self, folder="./", prefix=""):
			if folder[-1:] != "/":
				_log(f"Correcting folder name {folder} —> {folder}/", 0)
				folder += "/"

			filenames = {
				"unique_captions": "unique_captions",
				"unique_captions_clean": "unique_captions_clean",
				"all_captions": "all_captions",
				"all_captions_clean": "all_captions_clean",
			}

			prefix = dt.now().strftime(prefix)

			filenames = {k: Path(folder+prefix+v+".txt") for k,v in filenames.items()}

			all_captions = self.captions_as_text(all=True)
			all_captions_clean = self.captions_as_text(all=True, clean=True)

			unique_captions = self.captions_as_text(unique=True)
			unique_captions_clean = self.captions_as_text(unique=True, clean=True)

			_log(f"Saving all captions in {filenames['all_captions']}", 0)
			with open(filenames['all_captions'], 'w+') as file: file.write(all_captions)

			_log(f"Saving all captions (cleaned) in {filenames['all_captions_clean']}", 0)
			with open(filenames['all_captions_clean'], 'w+') as file: file.write(all_captions_clean)

			_log(f"Saving unique captions in {filenames['unique_captions']}", 0)
			with open(filenames['unique_captions'], 'w+') as file: file.write(unique_captions)

			_log(f"Saving unique captions (cleaned) in {filenames['unique_captions_clean']}", 0)
			with open(filenames['unique_captions_clean'], 'w+') as file: file.write(unique_captions_clean)


		def captions_as_text(self, **kwargs):
			_r = ""

			# Return all captions if requested
			if "all" in kwargs and kwargs["all"]: _r = " ".join([k for k, v in self.captions.items()])

			# Return unique captions if requested
			if "unique" in kwargs and kwargs["unique"]:
				for k, v in self.captions.items():
					if v == 1: _r += k + " "
				_r = _r[:-1]

			# Clean data if requested
			if "clean" in kwargs and kwargs["clean"]: _r = clean_text(_r, set_all=True)
			return(_r)

		def longest_words(self, num=1):
			all_captions = list(set(self.captions_as_text(unique=True, clean=True).split(" ")))
			if num == 1:
				longest_word =  max(all_captions, key=len)
				return(longest_word)
			elif num > 1:
				all_captions.sort(key=len, reverse=True)
				return(all_captions[0:num])


	class Geo(object):
		def __init__(self):
			self.coordinates = {}
			self.details = {}

		def __str__(self):
			return(f"""Geo locations:
{self.coordinates}
			""")

		def __getitem__(self, position):
			return self.coordinates[position]

		def __len__(self):
			return len(self.coordinates)

		def update_coordinates(self, location_object):
			if location_object is not None:
				if location_object.lat is not None and location_object.lng is not None:
					pos = f"{location_object.lat}, {location_object.lng}"

					if not pos in self.coordinates: self.coordinates[pos] = 1
					elif pos in self.coordinates: self.coordinates[pos] += 1
					else: raise RuntimeError("An unexpected error occurred while trying to update the number of posts posted in a coordinate.")

					if not pos in self.details:
						self.details[pos] = location_object

		@property
		def coordinates_sorted(self):
			return(sorted(self.coordinates.items(), key=itemgetter(1), reverse=True))

		@property
		def list(self):
			_r = "lat,lng,name,count\n"
			for _, obj in self.details.items():
				obj.name = obj.name.replace('"','\\"')
				count = self.coordinates[f"{obj.lat}, {obj.lng}"]
				_r += f"\"{obj.name}\",{obj.lat},{obj.lng},{count}" + "\n"
			return(_r)


		def find_by_coordinates(self, lat=None, lng=None):
			try:
				return(self.details[f"{lat}, {lng}"])
			except:
				return(None)

	class Network(object):
		def __init__(self):
			self._edges = {}
			self._nodes = {}
			self._mixin_data = None
			self._fields = []

		def mixin(self, path="./"):
			p = Path(path)
			if not p.is_file(): raise RuntimeError(f"There is no file {path}")
			with open(p, "r") as f:
				lines = f.read().split('\n')
			i=0
			_, headers = {}, []
			for line in lines:
				line_contents = line.split(',')
				if i is 0:
					num_fields = len(line_contents) - 1
					for header in line_contents[1:]:
						headers.append(header)
						if header not in self._fields: self._fields.append(header)
				else:
					if not line_contents[0] in _: _[line_contents[0]] = {}
					ii = 1
					for header in headers:
						try:
							_[line_contents[0]].update({header: line_contents[ii]})
						except IndexError:
							print(f"Warning: Numbers of headers do not match some lines in the mixin data (LINE {i+1}).")
						ii+=1
				i+=1
			self._mixin_data = _
			self.add_mixins()
		
		def update_edge(self, source, target, add=1, category="caption-mention"):
			source, target = source.lower(), target.lower()
			if source not in self._edges: self._edges[source] = {}
			if target not in self._edges[source]: self._edges[source][target] = {}
			if category not in self._edges[source][target]: self._edges[source][target][category] = 0
			self._edges[source][target][category] += add
		
		def add_mixins(self):
			for node in self._nodes:
				try:
					self._nodes[node].update(self._mixin_data[node])
				except KeyError:
					pass # The mixin data did not contain information about the particular node, just go ahead
				
		def update_nodes(self, post_object, download=False):
			names = [post_object.user.username]
			if post_object.caption is not None:
				names.extend(get_mentions(post_object.caption)) # extend names list with mentions

			for username in names:
				u = None
				cached = cache_exists("user", username)

				if not cached and download: # If we have set download to True and the user data is not in the cache, we want to create a user
					u = InstagramUser(username)
				elif not cached and not download:
					_log(f"Debug warning: Skipped downloading user {username} and could not add node information.", 0)
					if username not in self._nodes:
						self._nodes[username] = {
							"id": username,
							"cached": cached
						}
				elif cached:
					u = InstagramUser(username)
				else:
					raise RuntimeError("Unexpected error while trying to update node information for dataset.")

				if u is not None and u.ok:
					if u.username not in self._nodes:
						self._nodes[u.username] = {
							"id": u.username,
							"full_name": u.full_name,
							"cached": cached,
							"following": u.following,
							"followers": u.followers,
							"total_posts": u.total_posts,
							"account_business": u.is_business_account,
							"account_verified": u.is_verified,
							"account_private": u.is_private,
							"account_joined_recently": u.is_joined_recently,
						}
			if 'full_name' not in self._fields: self._fields.append('full_name')
			if 'cached' not in self._fields: self._fields.append('cached')
			if 'following' not in self._fields: self._fields.append('following')
			if 'followers' not in self._fields: self._fields.append('followers')
			if 'total_posts' not in self._fields: self._fields.append('total_posts')
			if 'account_business' not in self._fields: self._fields.append('account_business')
			if 'account_verified' not in self._fields: self._fields.append('account_verified')
			if 'account_private' not in self._fields: self._fields.append('account_private')
			if 'account_joined_recently' not in self._fields: self._fields.append('account_joined_recently')
			
		def __str__(self):
			_r = self.all()
			_return = "source,target,weight\n"
			i = 0
			for sourcetarget, count in _r.items():
				i+=1
				if i > 10:
					add_periods = True
					continue
				_return += f"{sourcetarget},{count}\n"
			if add_periods: _return += "..."
			return(_return)

		def update_edges(self, post_object):
			if post_object.caption is not None:
				for mention in get_mentions(post_object.caption):
					self.update_edge(post_object.user.username, mention, 1, category="caption-mention")
			for node in post_object.tagged_users:
				self.update_edge(post_object.user.username, node['username'], 1, category="tag")

		def all(self, category=False):
			""" Shows all edges. If category=True return list with edges by category """
			_category = category
			_r = {}
			for source, _ in self._edges.items():
				for target, __ in _.items():
					for category, count in __.items():
						if _category: pos = f"{source},{target},{category}"
						else: pos = f"{source},{target}"
						if pos not in _r: _r[pos] = 0
						_r[pos] += count
			return(_r)

		@property
		def nodes(self):
			""" Alias to see _nodes variable """
			return(self._nodes)

		@property
		def edges(self):
			""" Alias to see _edges variable """
			return(self._edges)

		def to_csv(self, folder="./", prefix=""):
			if folder[-1:] != "/":
				_log(f"Warning: Correcting folder name {folder} —> {folder}/", 10)
				folder += "/"

			filenames = {
				"edges_by_category": "edges_by_category",
				"edges": "edges",
				"nodes": "nodes"
			}
			
			prefix = dt.now().strftime(prefix)
			
			filenames = {k: Path(folder+prefix+v+".csv") for k,v in filenames.items()}

			_log(f"Saving all edges in {filenames['edges']}", 0)
			edges = self.all(category=False)
			with open(filenames['edges'], 'w+') as file:
				file.write("source,target,weight\n")
				for edge, count in edges.items():
					file.write(f"{edge},{count}\n")

			_log(f"Saving edges by category in {filenames['edges_by_category']}", 0)
			edges = self.all(category=True)
			with open(filenames['edges_by_category'], 'w+') as file:
				file.write("source,target,category,weight\n")
				for edge, count in edges.items():
					file.write(f"{edge},{count}\n")
			
			_log(f"Saving nodes in {filenames['nodes']}", 0)
			with open(filenames['nodes'], 'w+') as file:
				# Write headers
				__header = "id,label,"
				__header += ",".join(self._fields)
				file.write(f"{__header}\n")
				
				for _, data in self._nodes.items():
					__items = [data['id'], data['id']]
					for field in self._fields:
						try: __items.append(str(data[field]))
						except: __items.append('')
					__items = ",".join(__items)
					file.write(__items+"\n")


##### SET UP INSTAGRAM OBJECTS #########

class InstagramPost(object):

	def __init__(self, s, expand=False):

		# Check whether we have correct input
		if len(s) == 0: raise SyntaxError("You have to provide a correct shortcode for InstagramPost.")
		if not isinstance(expand, bool): raise SyntaxError("Expand must be set to a boolean mode.")

		# Set up empty containers
		self._raw, self.path, self.type, self.accessibility_caption, self.caption, self.caption_is_edited, self.height, self.width, self.latest_comments, self.num_likes, self.num_comments, self.tagged_users, self.sponsored_users, self.related_media, self.has_ranked_comments, self.is_ad, self.is_video, self.date_timestamp, self.date, self.date_obj = None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None
		self.cache_downloaded, self.cache_age = None, None
		self._all_hashtags = []
		if expand is True:
			self.user, self.location = None, None

		self.shortcode = s

		self.path = get_json_path(type="post", shortcode=s)

		# Get data
		data = _get_instagram_data(type="post", shortcode=s)
		if data is not None and len(data) > 0:
			self._raw = data

			if expand is True:
				# Set up InstagramPost.user
				if 'owner' in data and data['owner'] is not None: self.user = InstagramUser(data['owner'])

				# Set up InstagramPost.location
				if 'location' in data and data['location'] is not None: self.location = InstagramLocation(data['location']['slug'], data['location']['id'])

			self.type				   = data.get('__typename')

			self.accessibility_caption  = data.get('accessibility_caption')
			# self.accessibility_caption  = data['accessibility_caption'] if 'accessibility_caption' in data else None (same thing above?)

			self.caption = data['caption']

			self.caption_is_edited	  = data.get('caption_is_edited')
			self.dimensions			 = data.get('dimensions')
			self.height				 = self.dimensions.get('height')
			self.width				 = self.dimensions.get('width')
			self.latest_comments		= data.get('comments')
			self.num_likes			  = data.get('num_likes')
			self.num_comments		   = data.get('num_comments')
			self.tagged_users		   = data.get('tagged')
			self.sponsored_users		= data.get('sponsor_users')
			# self.related_media		  = data['']
			self.has_ranked_comments	= data.get('has_ranked_comments')
			self.is_ad				  = data.get('is_ad')
			self.date_timestamp		 = data.get('taken_at_timestamp')
			self.date_str			   = dt.fromtimestamp(self.date_timestamp).strftime('%Y-%m-%d %H:%M:%S')
			self.date				   = dt.fromtimestamp(self.date_timestamp)

			self.cache_downloaded	   = _downloaded("post", s, return_type="readable")
			self.cache_age			  = _age("post", s)

		else:
			self._raw = None

	@property
	def ok(self):
		return True if self._raw is not None else False

	@property
	def all_hashtags(self):
		if len(self._all_hashtags) == 0:
			if self.caption is not None:
				self._all_hashtags.extend(get_hashtags(text=self.caption, lower=True))
		return(self._all_hashtags)

	def __len__(self):
		if self.caption is not None: return(len(self.caption)) if self._raw is not None else 0
		else: return(0)

	def __repr__(self):
		return(f"InstagramPost({self.shortcode})")

	def __str__(self):
		return(f"InstagramPost object\n - shortcode = {self.shortcode}\n - date = {self.date}\n - type = {self.type}")

	def populate(self, _dict):
		""" Takes a dictionary of keys and returns it filled out with the values from the object."""

		if isinstance(_dict, set): _dict = dict.fromkeys(_dict, None)

		for k in _dict.keys():
			try:
				_dict[k] = getattr(self,k)
			except:
				raise Warning(f"Attribute {k} not available in object {self}.") from None
		return(_dict)

class InstagramUser(object):
	def __init__(self, s):

		# Check whether we have correct input
		if len(s) == 0: raise SyntaxError("You have to provide a correct shortcode for InstagramUser.")

		# Set up empty containers
		self._raw, self.bio, self.following, self.followers, self.total_posts, self.url, self.full_name, self.is_business_account, self.is_joined_recently, self.is_private, self.is_verified, self.profile_pic_url, self.profile_pic_url_hd = None, None, None, None, None, None, None, None, None, None, None, None, None
		self.cache_downloaded, self.cache_age = None, None

		self.username = s

		# Get data
		data = _get_instagram_data(type="user", shortcode=s)
		if data is not None and len(data) > 0:
			self._raw = data

			self.bio				  = data['biography']
			self.following			= data['edge_follow']['count']
			self.followers			= data['edge_followed_by']['count']
			self.total_posts		  = data['edge_owner_to_timeline_media']['count']
			self.url				  = data['external_url']
			self.full_name			= data['full_name']
			self.is_business_account  = data['is_business_account']
			self.is_joined_recently   = data['is_joined_recently']
			self.is_private		   = data['is_private']
			self.is_verified		  = data['is_verified']
			self.profile_pic_url	  = data['profile_pic_url']
			self.profile_pic_url_hd   = data['profile_pic_url_hd']

			self.cache_downloaded	 = _downloaded("user", s, return_type="readable")
			self.cache_age			= _age("user", s)
		else:
			self._raw = None


	def __len__(self):
		return(len(self.bio)) if self._raw is not None else 0


	@property
	def ok(self):
		return True if self._raw is not None else False


class InstagramLocation(object):
	def __init__(self, s, id):

		# Check whether we have correct input
		if len(s) == 0 and len(id) == 0: raise SyntaxError(f"You have to provide a correct shortcode or id for InstagramLocation. You provided `{s}` (shortcode) and `{id}` (id).")

		# Set up empty containers
		self._raw, self.address_json, self.blurb, self.total_posts, self.has_public_page, self.id, self.lat, self.lng, self.name, self.phone, self.primary_alias_on_fb, self.shortcode, self.website, self.profile_pic_url = None, None, None, None, None, None, None, None, None, None, None, None, None, None
		self.cache_downloaded, self.cache_age = None, None
		self.country, self.city, self.zipcode = None, None, None

		# Get data
		data = _get_instagram_data(type="place", shortcode=s, id=id)
		if data is not None and len(data) > 0:
			self._raw = data

			try:
				self.address			  = json.loads(data['address_json'])
			except:
				self.address = {'country_code': '', 'city_name': '', 'zip_code': ''}
			self.country = self.address['country_code']
			self.city = self.address['city_name']
			self.zipcode = self.address['zip_code']
			self.blurb				= data['blurb']
			self.total_posts		  = data['edge_location_to_media']['count']
			self.has_public_page	  = data['has_public_page']
			self.id				   = data['id']
			self.lat				  = data['lat']
			self.lng				  = data['lng']
			self.name				 = data['name']
			self.phone				= data['phone']
			self.primary_alias_on_fb  = data['primary_alias_on_fb']
			self.shortcode			= data['slug']
			self.website			  = data['website']
			self.profile_pic_url	  = data['profile_pic_url']

			self.cache_downloaded	 = _downloaded("place", s, return_type="readable")
			self.cache_age			= _age("place", s)
		else:
			self._raw = None


	def __len__(self):
		return(len(self.blurb)) if self._raw is not None else 0


	@property
	def ok(self):
		return True if self._raw is not None else False


### From former version

def expand_filepaths(filepaths):
	if isinstance(filepaths, str) == True:
		try:
			files = listdir_nohidden(filepaths)
		except FileNotFoundError:
			raise RuntimeError(f"Directory or file with posts {filepaths} could not be found.", 0) from None
	elif isinstance(filepaths, list) == True:
		try:
			files = []
			for p in filepaths:
				fullpath = listdir_fullpath(p)
				files.extend(fullpath)
		except FileNotFoundError:
			raise RuntimeError(f"Directory or file with posts {filepaths} could not be found.", 0) from None
	else:
		raise RuntimeError("Error: "+str(filepaths), 0) from None
	return(files)



def get_shortcodes_from_hashtags(hashtags=None):
	if hashtags == None: raise SyntaxError("You have to provide at least one hashtag (as a string) or a list of hashtags containing at least one element.")
	if isinstance(hashtags, str): hashtags = [hashtags]
	_ = []
	for hashtag in hashtags:
		path = cfg["hashtags_datasets"] / hashtag
		shortcodes = get_shortcodes_from_path(path)
		_.extend(shortcodes)

	return(list(set(_)))

def get_shortcodes_from_users(users=None):
	if users == None: raise SyntaxError("You have to provide at least one username (as a string) or a list of usernames containing at least one element.")
	if isinstance(users, str): users = [users]
	_ = []
	for user in users:
		path = cfg["users_datasets"] / user / 'feed'
		shortcodes = get_shortcodes_from_path(path)
		_.extend(shortcodes)

	return(list(set(_)))


def get_shortcodes_from_path(path):
	p = Path(path)
	files = listdir_nohidden(p)
	shortcodes = []
	
	for file in files:
		fp = Path(file).name

		if fp[0:1] == ".": pass # Found a hidden file

		elif fp[0:1] == "_": # Found a cache file!
			with open(f"{p}/{fp}", "r") as f: shortcodes.extend(f.read().split("\n"))

		else: # Found another file, try to open it and read
			try:
				with open(f"{p}/_{fp}", "r") as f: pass # Trying to check whether we have a cache'd version of this one (if so, it takes priority!)
			except:
				try:
					with open(file, "r") as f:
						content = f.read()
						g = re.findall(pattern='a href="\/p\/(\S*)\/', string=content) # Sear for "/p/________/"
						if len(g) > 0:
							_log(f"Debug: Found {len(g)} shortcodes in {file}.")
						else:
							g = re.findall(pattern='a href="\/p\/(\S*)">|\?=\S+"', string=content) # We're now searching for "/p/______"
							if len(g) > 0:
								_log(f"Debug: Found {len(g)} shortcodes in {file}.")
							else:
								_log(f"Warning: RegEx found no shortcodes ({g}) in file {file}.", 10)
						
					with open(f"{p}/_{fp}", "w+") as f:
						f.write("\n".join(g))
					shortcodes.extend(g)
				except Exception as e:
					print(e)
					exit()
					
	# shortcodes = list(filter(None, shortcodes))
	
	return(list(set(shortcodes)))


def listdir_fullpath(d):
	return [os.path.join(d, f) for f in os.listdir(d)]


def listdir_nohidden(path):
	return glob.glob(os.path.join(path, '*'))




### NEW VERSION

def _save_empty_json(path=None):
	""" Save an empty JSON file """

	# Verify all settings
	if path == None: raise SyntaxError('A path must be provided.')

	_json = ""
	with open(path, 'w+') as outfile: json.dump(_json, outfile)


def wait_for_download(min=cfg['downloads_wait_min'], max=cfg['downloads_wait_max'], randomize=True):
	if not isinstance(min, int):
		_log(f"Warning: Minimum wait time was set to {min}. Setting to 1 and moving on.", 10)
		min = 1
	if not isinstance(max, int):
		_log(f"Warning: Maximum wait time was set to {max}. Setting to 3 and moving on.", 10)
		max = 3
	if randomize:
		if min < max:
			wait = randrange(min, max)
		elif min == max:
			wait = min
		elif min > max:
			wait = randrange(max, min)
	else:
		wait = min
		_log(f"Waiting for set number {wait}.", 0)
	time.sleep(wait)


def get_json_path(type=None, shortcode=None):
	""" Returns the path to the local JSON file for the shortcode/type.

	Args:
		type (str): Set to either "post", "user", or "place" depending on which type of Instagram post you want to return
		shortcode (str): An Instagram shortcode

	Returns:
		str: The path to the JSON file for the shortcode/type.
	"""

	# Verify all settings
	if type == None: raise SyntaxError('A type must be provided.')
	if shortcode == None: raise SyntaxError('A shortcode must be provided.')
	if (type != "post" and 
		type != "user" and 
		type != "place" and 
		type != "tweet" and 
		type != "tweeter" and
		type != "twitter-place"): raise SyntaxError('An unknown type format was provided.')

	return(cfg['cache_folder'].joinpath(f"__{type}s/{shortcode}.json"))


def get_instagram_link(type=None, shortcode=None, id=None):
	""" Returns the link to the Instagram page for the Instagram data. """

	# Verify all settings
	if type == None: raise SyntaxError('A type must be provided.')
	if shortcode == None: raise SyntaxError('A shortcode must be provided.')
	if type is not "post" and type is not "user" and type is not "place": raise SyntaxError('An unknown type format was provided.')
	if type is "place" and id is None: raise SyntaxError('An ID must be provided together with a shortcode for Instagram places.')

	if type == "post": return(f"http://www.instagram.com/p/{shortcode}")
	elif type == "user": return(f"http://www.instagram.com/{shortcode}")
	elif type == "place": return(f"http://www.instagram.com/explore/locations/{id}/{shortcode}")


def _save_json(_json=None, path=None):
	""" Internal function for saving JSON file to a desired path. """

	# Verify all settings
	if _json == None: raise SyntaxError('JSON data must be provided.')
	if path == None: raise SyntaxError('A path must be provided.')

	try:
		with open(path, 'w+') as outfile: json.dump(_json, outfile)
		return(True)
	except:
		raise Exception(f'JSON file {path} could not be saved.')


def download_json(type=None, shortcode=None, id=None):
	""" Download JSON data from Instagram """

	# Verify all settings
	if type == None: raise SyntaxError('A type must be provided.')
	if shortcode == None: raise SyntaxError('A shortcode must be provided.')

	# Set up standards
	_json, script = None, None

	# Get path where JSON should be stored
	desired_path = get_json_path(type, shortcode)

	# Get the full link to the Instagram post
	link = get_instagram_link(type=type, shortcode=shortcode, id=id)

	# Wait
	wait_for_download()

	# Download HTML
	_log(f"Attempting to download Instagram post {shortcode}...", 0)
	html = requests.get(link).content

	# Soupify
	soup = BeautifulSoup(html, 'lxml')

	if str(html).find("link you followed may be broken") > 0: _save_empty_json(desired_path)
	elif str(html).find("something went wrong") > 0: _save_empty_json(desired_path)
	elif str(html).find("video is not available in your country") > 0: _save_empty_json(desired_path)
	else:
		scripts = soup.findAll("script")
		for s in scripts:
			if str(s).find("shortcode") > 0:
				script = s
				_json = json.loads(str(script)[52:-10]) # #hard-coded cropping of Javascript here - might need to change in future revisions of Instagram source code

		if _json is not None and "entry_data" in _json:
			if type == "post": _json = _clean_post(_json["entry_data"]["PostPage"][0]["graphql"]["shortcode_media"])
			elif type == "user": _json = _json["entry_data"]["ProfilePage"][0]["graphql"]["user"]
			elif type == "place": _json = _json["entry_data"]["LocationsPage"][0]["graphql"]["location"]
			_save_json(_json, desired_path)
		elif _json is None:
			_save_empty_json(desired_path) # We found an empty Instagram type here...
		else:
			raise RuntimeError(f"Fatal error: Instagram {type} with shortcode {shortcode} could not be downloaded. JSON: \n{_json}\n")




def is_in_cache(type=None, shortcode=None):
	path = get_json_path(type=type, shortcode=shortcode)
	try:
		with open(path) as f: data = f.read()
		return(True)
	except FileNotFoundError:
		return(False)

def in_cache():
	pass


def _get_instagram_data(type=None, shortcode=None, id=None, force_download=False):
	""" Fetches the correct JSON from the cache, or redirects to an attempt to download the cache file if it does not already exist. """

	# Settings are not verified here as they are verified in the later steps when they are needed (see get_json_path and download_json functions)

	data = None
	path = get_json_path(type=type, shortcode=shortcode)
	
	if force_download: download_json(type=type, shortcode=shortcode, id=id)
	
	try:
		with open(path) as json_data: data = json.load(json_data)
		return(data)
	except FileNotFoundError:
		download_json(type=type, shortcode=shortcode, id=id)
		try:
			with open(path) as json_data: data = json.load(json_data)
			return(data)
		except FileNotFoundError as e:
			_log(f"Error: Tried to download but something failed twice with {type} with shortcode {shortcode}:\n\n{e}", 20)
			return(None)


def _downloaded(type=None, shortcode=None, return_type="readable"):
	""" Returns the download date of a JSON cache file as a standard timestamp """

	# Verify all settings
	if type == None: raise SyntaxError('A type must be provided.')
	if shortcode == None: raise SyntaxError('A shortcode must be provided.')

	timestamp = os.path.getctime(get_json_path(type, shortcode))
	if return_type is "readable":
		return(dt.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S'))
	elif return_type is "timestamp":
		return(timestamp)
	else:
		raise SyntaxError(f'Could not understand return type {return_type}.')


def _age(type=None, shortcode=None):
	""" Returns the age of a JSON cache file """

	# Verify all settings
	if type == None: raise SyntaxError('A type must be provided.')
	if shortcode == None: raise SyntaxError('A shortcode must be provided.')

	return(int(-((os.path.getctime(get_json_path(type, shortcode)) - time.time()) / 3600) / 24))


def get_empty_cache_files(type="posts"):
	""" Returns a list of empty cache files (i.e. the ones with a size of 2 bytes). """

	if type is not "posts" and type is not "users" and type is not "places": raise SyntaxError('An unknown type format was provided.')

	names = os.listdir(f"{cfg['cache_folder']}__{type}")
	paths = [os.path.join(f"{cfg['cache_folder']}__{type}", name) for name in names]
	sizes = [(path, os.stat(path).st_size) for path in paths]

	grouped = collections.defaultdict(list)
	for path, size in sizes:
		grouped[size].append(path)
	size_two = grouped[2]
	return(size_two)


def delete_file(path):
	""" Deletes a file, if provided with a path. USE WITH CAUTION. """
	try:
		os.remove(path)
	except OSError as e:
		_log(f"Error: {e.filename} - {e.strerror}.", 20)


def clean_cache_from_pattern(type="all", pattern=None):
	""" Removes all files from a specified pattern

	Returns: Number of files deleted.
	
	Example:
	- clean_cache_from_pattern(type="posts", pattern="*conflicted*")
	"""

	if pattern == None: raise SyntaxError('A pattern must be provided.')
	if type is not "all" and type is not "posts" and type is not "users" and type is not "places": raise SyntaxError('An unknown type format was provided.')

	count = 0
	remove_files = []

	if type is "all":
		remove_posts = glob.glob(f"{cfg['cache_folder']}__posts/{pattern}")
		remove_places = glob.glob(f"{cfg['cache_folder']}__places/{pattern}")
		remove_users = glob.glob(f"{cfg['cache_folder']}__users/{pattern}")

		remove_files.extend(remove_posts)
		remove_files.extend(remove_places)
		remove_files.extend(remove_users)
	else:
		remove_files = glob.glob(f"{cfg['cache_folder']}__{type}/{pattern}")

	for file in remove_files:
		delete_file(file)
		count += 1
	return(count)

def shortcodes_from_hashtag(h):
	""" Generator function to yield the shortcodes in a hashtag for each hashtag """
	shortcodes = get_shortcodes_from_hashtags(h)
	for s in shortcodes: yield s


# Functions -- Processing data

def get_hashtags(text=None, lower=False):
	if lower: text = text.lower()
	tags = re.findall(r'\B#([^\W]+)', text)
	return(tags)

def get_mentions(text=None, lower=False):
	if lower: text = text.lower()
	tags = re.findall(r'\B@([(\w|.)]+)', text)
	return(tags)

def clean_text(text, **kwargs):
	if len(kwargs) == 0: kwargs['set_all'] = True # If no keyword arguments are provided, we will clean out everything

	lower=False
	no_links=False
	no_digits=False
	expand_contractions=False
	remove_stopwords=False
	if "lower" in kwargs and kwargs['lower']: lower = True
	if "no_links" in kwargs and kwargs['no_links']: no_links = True
	if "no_digits" in kwargs and kwargs['no_digits']: no_digits = True
	if "expand_contractions" in kwargs and kwargs['expand_contractions']: expand_contractions = True
	if "remove_stopwords" in kwargs and kwargs['remove_stopwords']: remove_stopwords = True

	strip_emoji=True
	no_hash=True
	no_at=True
	no_punc=True
	strip_spaces=True
	if "strip_emoji" in kwargs and kwargs['strip_emoji']: strip_emoji = True
	if "no_hash" in kwargs and kwargs['no_hash']: no_hash = True
	if "no_at" in kwargs and kwargs['no_at']: no_at = True
	if "no_punc" in kwargs and kwargs['no_punc']: no_punc = True
	if "strip_spaces" in kwargs and kwargs['strip_spaces']: strip_spaces = True

	if "set_all" in kwargs and kwargs['set_all']:
		lower=True
		no_links=True
		no_digits=True
		no_at=True
		no_hash=True
		expand_contractions=True
		remove_stopwords=True
	elif "set_all" in kwargs and not kwargs['set_all']:
		lower=False
		no_links=False
		no_digits=False
		no_at=False
		no_hash=False
		expand_contractions=False
		remove_stopwords=False

	if "strip_emoji" in kwargs and not kwargs['strip_emoji']: strip_emoji = False

	def special_replacements(text):
		replacements = {
			"motherf ing": "motherf-ing"
		}
		for k, v in replacements.items():
			text = text.replace(k, v)
		return(text)

	if text is not None:
		text = str(text).replace("\n"," ")

		if no_links: text = re.sub(r"(?i)\b((?:[a-z][\w-]+:(?:\/{1,3}|[a-z0-9%])|www\d{0,3}[.]|[a-z0-9.\-]+[.][a-z]{2,4}\/)(?:[^\s()<>]+|\(([^\s()<>]+|(\([^\s()<>]+\)))*\))+(?:\(([^\s()<>]+|(\([^\s()<>]+\)))*\)|[^\s`!()\[\]{};:'\".,<>?«»“”‘’]))", "", text) # also replace www.????.co/m
		if lower: text = text.lower()

		if no_hash: text = re.sub(r"#[\w-]+", "", text)
		if no_at: text = re.sub(r"@[\w-]+", "", text)
		if no_digits: text = re.sub(r"[{}]".format(string.digits)," ", text)

		if strip_emoji:
			returnString=""
			for character in text:
				try:
					character.encode("ascii")
					returnString += character
				except UnicodeEncodeError:
					returnString += ' '
			text = returnString

		if expand_contractions:
			text = expandContractions(text.replace("’", "'"))

		if no_punc:
			text = re.sub("[{}]".format(string.punctuation)," ", text)
			text = re.sub("[¡“”’]"," ", text)

		if remove_stopwords:
			stops = stopwords.words('english')
			stops.extend([
				'pm',
				'w',
				'rd',
				'th',
				'jan',
				'feb',
				'mar',
				'apr',
				'may',
				'jun',
				'jul',
				'aug',
				'sep',
				'oct',
				'nov',
				'dec',
				'mon',
				'tue',
				'wed',
				'thu',
				'fri',
				'sat',
				'sun'
			])
			stops = set(stops)
			filtered_words = [word for word in text.split() if word not in stops]
			text = " ".join(filtered_words)

		if strip_spaces:
			text = re.sub(" +"," ", text)
			text = text.strip()

		text = special_replacements(text)

		return(text)
	else:
		return(None)

def expandContractions(text, c_re=None):
	cList = {
		"ain't": "am not",
		"aren't": "are not",
		"can't": "cannot",
		"can't've": "cannot have",
		"'cause": "because",
		"could've": "could have",
		"couldn't": "could not",
		"couldn't've": "could not have",
		"didn't": "did not",
		"doesn't": "does not",
		"don't": "do not",
		"hadn't": "had not",
		"hadn't've": "had not have",
		"hasn't": "has not",
		"haven't": "have not",
		"he'd": "he would",
		"he'd've": "he would have",
		"he'll": "he will",
		"he'll've": "he will have",
		"he's": "he is",
		"how'd": "how did",
		"how'd'y": "how do you",
		"how'll": "how will",
		"how's": "how is",
		"i'd": "i would",
		"i'd've": "i would have",
		"i'll": "i will",
		"i'll've": "i will have",
		"i'm": "i am",
		"i've": "i have",
		"isn't": "is not",
		"it'd": "it had",
		"it'd've": "it would have",
		"it'll": "it will",
		"it'll've": "it will have",
		"it's": "it is",
		"let's": "let us",
		"ma'am": "madam",
		"mayn't": "may not",
		"might've": "might have",
		"mightn't": "might not",
		"mightn't've": "might not have",
		"must've": "must have",
		"mustn't": "must not",
		"mustn't've": "must not have",
		"needn't": "need not",
		"needn't've": "need not have",
		"o'clock": "of the clock",
		"oughtn't": "ought not",
		"oughtn't've": "ought not have",
		"shan't": "shall not",
		"sha'n't": "shall not",
		"shan't've": "shall not have",
		"she'd": "she would",
		"she'd've": "she would have",
		"she'll": "she will",
		"she'll've": "she will have",
		"she's": "she is",
		"should've": "should have",
		"shouldn't": "should not",
		"shouldn't've": "should not have",
		"so've": "so have",
		"so's": "so is",
		"that'd": "that would",
		"that'd've": "that would have",
		"that's": "that is",
		"there'd": "there had",
		"there'd've": "there would have",
		"there's": "there is",
		"they'd": "they would",
		"they'd've": "they would have",
		"they'll": "they will",
		"they'll've": "they will have",
		"they're": "they are",
		"they've": "they have",
		"to've": "to have",
		"wasn't": "was not",
		"we'd": "we had",
		"we'd've": "we would have",
		"we'll": "we will",
		"we'll've": "we will have",
		"we're": "we are",
		"we've": "we have",
		"weren't": "were not",
		"what'll": "what will",
		"what'll've": "what will have",
		"what're": "what are",
		"what's": "what is",
		"what've": "what have",
		"when's": "when is",
		"when've": "when have",
		"where'd": "where did",
		"where's": "where is",
		"where've": "where have",
		"who'll": "who will",
		"who'll've": "who will have",
		"who's": "who is",
		"who've": "who have",
		"why's": "why is",
		"why've": "why have",
		"will've": "will have",
		"won't": "will not",
		"won't've": "will not have",
		"would've": "would have",
		"wouldn't": "would not",
		"wouldn't've": "would not have",
		"y'all": "you all",
		"y'alls": "you alls",
		"y'all'd": "you all would",
		"y'all'd've": "you all would have",
		"y'all're": "you all are",
		"y'all've": "you all have",
		"you'd": "you had",
		"you'd've": "you would have",
		"you'll": "you you will",
		"you'll've": "you you will have",
		"you're": "you are",
		"you've": "you have",
		"aint": "am not",
		"arent": "are not",
		"cant": "cannot",
		"couldve": "could have",
		"couldnt": "could not",
		"didnt": "did not",
		"doesnt": "does not",
		"dont": "do not",
		"hadnt": "had not",
		"hasnt": "has not",
		"havent": "have not",
		"isnt": "is not",
		"shouldve": "should have",
		"shouldnt": "should not",
		"thats": "that is",
		"theyd": "they would",
		"theyre": "they are",
		"theyve": "they have",
		"whats": "what is",
		"wheres": "where is",
		"youll": "you you will",
		"youre": "you are",
		"youve": "you have",
	}
	if c_re is None: c_re = re.compile('(%s)' % '|'.join(cList.keys()))
	def replace(match):
		return cList[match.group(0)]
	return c_re.sub(replace, text)




def posts_mentioning(hashtags=[], mentions=None, hashtag=None, show_progress=True):
	# return posts within a dataset who mention a certain username or a hashtag (but can't be both)

	# If hashtags is a string, fix it to be in a list with one element
	if isinstance(hashtags, str): hashtags=[hashtags]

	results, processed = {}, []
	for h in hashtags:
		if show_progress:
			# Start a progressbar
			i=0
			bar = progressbar.ProgressBar(max_value=sum(1 for _ in shortcodes_from_hashtag(h))).start()

		for s in shortcodes_from_hashtag(h):
			if show_progress:
				# Update progressbar
				i+=1
				bar.update(i)

			if s not in processed:
				processed.append(s)

				post = InstagramPost(s, expand=True)
				if not post.ok: continue

				_m = get_mentions(post.caption)
				for mention in mentions:
					if mention in _m:
						if mention not in results: results[mention] = []
						results[mention].append(s)

	if show_progress: bar.finish()

	return(results)


def cache_exists(type=None, shortcode=None):
	""" Checks whether JSON cache file exists.
		- Returns: bool"""
	if type != "post" and type != "user" and type != "place" and type != "tweet" and type != "tweeter" and type != "twitter-place": raise RuntimeError(f"Cannot understand type `{type}`.")

	try:
		_ = os.path.getctime(get_json_path(type, shortcode))
		return(True)
	except OSError:
		return(False)





#### I could build this out to include Twitter here as well...

class TwitterDataset(object):
	""" Creates a Dataset object based on a list of hashtags."""

	def __init__(self, **kwargs):
		self._all_tweet_ids = []
		self._all_hashtags = []
		self._all_shortcodes = []
		self.expand_instagram = False

		if 'expand_instagram' in kwargs and kwargs['expand_instagram']: self.expand_instagram = True

		if 'tweets' in kwargs:
			if isinstance(kwargs['tweets'], str): self._all_tweet_ids = [kwargs['tweets']]
			elif isinstance(kwargs['tweets'], list): self._all_tweet_ids = kwargs['tweets']
			else: raise RuntimeError(f"The type of tweet data passed to the object is unknown.")

			if len(self.tweet_ids) < 1: raise RuntimeError(f"The list of tweets passed to the object must contain some tweets.")

		elif 'hashtags' in kwargs:
			if isinstance(kwargs['hashtags'], str): self._all_hashtags = [kwargs['hashtags']]
			elif isinstance(kwargs['hashtags'], list): self._all_hashtags = kwargs['hashtags']

			comments_in_hashtag_files = ('#', '%')
			for h in self._all_hashtags:
				hashtag_path = cfg['TWITTER_datasets'].joinpath(f"{h}.txt")
				with open(hashtag_path, 'r') as f:
					hashtag_ids = f.readlines()
				hashtag_ids = [x for x in hashtag_ids if not x.startswith(comments_in_hashtag_files)]
				hashtag_ids = [x.strip() for x in hashtag_ids]
				self._all_tweet_ids.extend(hashtag_ids)

		self.tweets = self._setup_tweets()


	def _setup_tweets(self):
		_r = []

		i = 0
		bar = progressbar.ProgressBar(max_value=len(self._all_tweet_ids)).start()
		for id in self._all_tweet_ids:
			i+=1
			bar.update(i)
			tweet = Tweet(id=id, expand_instagram = self.expand_instagram)
			_r.append(tweet)
			if self.expand_instagram:
				if tweet.instagram and tweet.instagram.shortcode: self._all_shortcodes.append(tweet.instagram.shortcode)

			# if tweet.retweet: #pass

			# do things with tweet here
		bar.finish()

		return(_r)

	def to_csv(self, folder="./", prefix=""):
		if folder[-1:] != "/":
			_log(f"Warning: Correcting folder name {folder} —> {folder}/", 10)
			folder += "/"

		filenames = {
			"all_tweets": "all_tweets"
		}

		prefix = dt.now().strftime(prefix)

		filenames = {k: Path(folder+prefix+v+".csv") for k,v in filenames.items()}

		_log(f"Saving all tweets in {filenames['all_tweets']}", 0)

		for tweet in self.tweets:
			print(tweet)
		'''
		with open(filenames['edges'], 'w+') as file:
			file.write("source,target,weight\n")
		'''



	@property
	def hashtags(self):
		return(self._all_hashtags)

	@property
	def tweet_ids(self):
		return(self._all_tweet_ids)


class TweetGeo(object):

	def __init__(self, place=None, coordinates=None): # verify that lat, lng are correct
		self._place = place
		self.lat = coordinates['coordinates'][0] if isinstance(coordinates, dict) else None
		self.lng = coordinates['coordinates'][1] if isinstance(coordinates, dict) else None

		self.id = self._place['id'] if isinstance(self._place, dict) else None

		self.type, self.contained_within, self.country, self.full_name, self.name = None, None, None, None, None
		if self.id:
			data = self._get_twitter_geodata(special_id=None)
			if data is not None:
				if 'bounding_box_centroid' in data and isinstance(data['bounding_box_centroid'], list):
					self.lng = data['bounding_box_centroid'][0]
					self.lat = data['bounding_box_centroid'][1]
				if 'place_type' in data: self.type = data['place_type']
				if 'contained_within' in data: self.contained_within = data['contained_within']
				if 'country' in data: self.country = data['country']
				if 'full_name' in data: self.full_name = data['full_name']
				if 'name' in data: self.name = data['name']
				if 'contained_within' in data: self.contained_within = self._get_twitter_geodata(special_id=self.contained_within)
			else:
				_log(f"Warning: Location data is empty.", 10)
		else:
			_log(f"Debug: Location ID is not set.", 0)

	def _get_twitter_geodata(self, special_id=None):
		if special_id: id = special_id
		else: id = self.id

		if not cache_exists(type="twitter-place", shortcode=id):
			data = self._download_place(id=id)
		else:
			json_path = get_json_path(type="twitter-place", shortcode=id)
			_log(f"Reading local cache for Tweet place ID {id}\n(DEBUG:\n\tid={self.id})\n\tspecial_id={special_id}\n\tfile={json_path}\n).", 0)
			with open(json_path, 'r') as cache_file:
				data = json.load(cache_file)
		return(data)


	def _download_place(self, id=None):
		if id == None: id = self.id

		_json = {}

		# Get cache path
		json_path = get_json_path(type="twitter-place", shortcode=id)

		# Setup tweepy API
		auth = tweepy.OAuthHandler(cfg['TWITTER_consumer_key'], cfg['TWITTER_consumer_secret'])
		auth.set_access_token(cfg['TWITTER_access_token'], cfg['TWITTER_access_token_secret'])
		api = tweepy.API(auth,wait_on_rate_limit=True, wait_on_rate_limit_notify=True)

		# Get place
		_log(f"Attempting to download Tweet place ID {id}...", 10)
		try:
			__place = api.geo_id(id)
			_json = {
				'place_type': __place.place_type,
				'bounding_box_type': __place.bounding_box.type,
				'bounding_box_coordinates': __place.bounding_box.coordinates,
				'bounding_box_centroid': __place.centroid,
				'country': __place.country,
				'country_code': __place.country_code,
				'full_name': __place.full_name,
				'geometry': __place.geometry,
				'name': __place.name,
				'geotag_count': None,
				'contained_within': None,
				'polylines': __place.polylines,
			}
			if 'geotagCount' in __place.attributes: _json['geotag_count'] = __place.attributes['geotagCount']
			if len(__place.contained_within) > 0: __place.contained_within[0]: _json['contained_within'] = __place.contained_within[0].id
			else: _log(f"Debug warning: __place.contained_within: {__place.contained_within}.", 10)

			# save json
			_log(f"Saving JSON in {json_path}...", 20)
			with open(json_path, 'w+') as cache_file:
				json.dump(_json, cache_file)
		except tweepy.TweepError as e:
			_log(f"Error processing tweet location with ID {id}: "+str(e.args[0][0]['message']), 20)
			with open(json_path, 'w+') as cache_file:
				_json = {'error': str(e.args[0][0]['message'])}
				json.dump(_json, cache_file)
		''' Unnecessary step but put here as a control... '''
		with open(json_path, 'r') as cache_file:
			data = json.load(cache_file)
		return(data)


class Tweet(object):

	def __init__(self, id=0, **kwargs):
		if id == 0: raise RuntimeError("ID cannot be set to 0.")

		self.id = id

		# Get data for tweet
		self._raw = self._get_twitter_data()

		# Set up standards
		self.date, self.date_obj, self.text, self.caption, self.place, self.error, self.retweeted_tweet = (
		None, None, None, None, None, None, None)
		self.mentions, self.hashtags = [], []
		self.retweet, self.instagram, self.expand_instagram = False, False, False
		self.num_likes, self.num_retweets = 0, 0

		if 'expand_instagram' in kwargs and kwargs['expand_instagram']: self.expand_instagram = True

		if "error" not in self._raw:
			self.ok = True

			# Simple ones
			self.caption = self._raw['full_text']
			self.lang = self._raw['lang']
			self.num_likes = self._raw['favorite_count']
			self.num_retweets = self._raw['retweet_count']

			# Set up geodata
			if self._raw['place']: self.place = TweetGeo(place=self._raw['place'], coordinates=self._raw['coordinates'])

			# Set up Tweet.user
			if 'user' in self._raw and isinstance(self._raw['user'], int):
				self.user = TwitterUser(self._raw['user'])

			# Set up retweet.Tweet
			if 'retweeted_status' in self._raw and isinstance(self._raw['retweeted_status'], int):
				self.retweeted_tweet = Tweet(self._raw['retweeted_status'])

			self.cache_downloaded = _downloaded("tweet", self.id, return_type="readable")
			self.cache_age = _age("tweet", self.id)

			self.date_obj = dt.strptime(
				self._raw["created_at"],
				'%a %b %d %H:%M:%S %z %Y').replace(
					tzinfo=timezone.utc
				).astimezone(
					tz=None
				)
			self.date = self.date_obj.strftime('%Y-%m-%d %H:%M:%S')

			# set up mentions
			for m in self._raw['entities']['user_mentions']:
				self.mentions.append((m['screen_name'], m['id']))

			# set up hashtags
			for h in self._raw['entities']['hashtags']:
				self.hashtags.append(h['text'])

			# set up links
			for l in self._raw['entities']['urls']:
				if 'instagram' in l['expanded_url']:
					i=0
					for elem in l['expanded_url'].split("/"):
						if elem == "p": self.instagram = l['expanded_url'].split("/")[i+1]
						i+=1
					if self.instagram and self.expand_instagram: self.instagram = InstagramPost(self.instagram, expand=True)
		else:
			self.ok = False
			self.error = _raw['error']

	@property
	def json(self):
		return(self._raw)

	def _get_twitter_data(self, id=None):
		if id == None: id = self.id

		if not cache_exists(type="tweet", shortcode=id):
			data = self._download_tweet(id=self.id)
		else:
			_log(f"Reading local cache for Tweet ID {id}.")
			json_path = get_json_path(type="tweet", shortcode=id)
			with open(json_path, 'r') as cache_file:
				data = json.load(cache_file)
		return(data)

	def _download_tweet(self, id=None):
		if id == None: id = self.id

		# Get cache path
		json_path = get_json_path(type="tweet", shortcode=id)

		# Setup tweepy API
		auth = tweepy.OAuthHandler(cfg['TWITTER_consumer_key'], cfg['TWITTER_consumer_secret'])
		auth.set_access_token(cfg['TWITTER_access_token'], cfg['TWITTER_access_token_secret'])
		api = tweepy.API(auth,wait_on_rate_limit=True, wait_on_rate_limit_notify=True)

		# Get tweet
		_log(f"Attempting to download Tweet ID {id}...")
		_break = False
		attempts = 1
		while _break == False:
			try:
				__tweet = api.get_status(id, tweet_mode='extended')
				_break = True
			except:
				wait_for_download()
				attempts += 1
				_log(f"Debug warning: Tweet download attempt failed. Attempt number {attempts} commences.")
				if attempts == cfg["max_attempts"]+1: _break = True

		if __tweet._json['user']['protected'] is True:
			_log(f"Found a protected tweet and will not download data.", 10)
			with open(json_path, 'w+') as cache_file:
					_json = {'error': 'protected user data'}
					json.dump(_json, cache_file)
		else:
			_json = __tweet._json

			# clean tweet here
			user_id = _json['user']['id']
			del(_json['user'])
			_json['user'] = user_id

			if 'retweeted_status' in _json and isinstance(_json['retweeted_status'], dict):
				retweeted_status_id = _json['retweeted_status']['id']
				del(_json['retweeted_status'])
				_json['retweeted_status'] = retweeted_status_id

			# save json
			with open(json_path, 'w+') as cache_file:
				json.dump(_json, cache_file)
		'''
		except tweepy.TweepError as e:
			_log(f"Error processing tweet ID {id}: "+str(e.args[0][0]['message']), 10)
			with open(json_path, 'w+') as cache_file:
				_json = {'error': str(e.args[0][0]['message'])}
				json.dump(_json, cache_file)
		'''
		return(_json)


class TwitterUser(object):

	def __init__(self, id=0):
		self.id = id

		self._raw = self._get_twitter_user(self.id)

		# Simple ones
		self.followers_count = self._raw['followers_count'] or None
		self.description = self._raw['description'] or None
		self.friends_count = self._raw['friends_count'] or None
		self.listed_count = self._raw['listed_count'] or None
		self.location = self._raw['location'] or None
		self.name = self._raw['name'] or None
		self.screen_name = self._raw['screen_name'] or None
		self.statuses_count = self._raw['statuses_count'] or None
		self.verified = self._raw['verified'] or None

	def _get_twitter_user(self, id=None):
		if id == None: id = self.id

		if not cache_exists(type="tweeter", shortcode=id):
			data = self._download_tweet_user(id=id)
		else:
			_log(f"Reading local cache for Tweet user with ID {id}.")
			json_path = get_json_path(type="tweeter", shortcode=id)
			with open(json_path, 'r') as cache_file:
				data = json.load(cache_file)
		return(data)


	def _download_tweet_user(self, id=None):
		if id == None: id = self.id

		# Get cache path
		json_path = get_json_path(type="tweeter", shortcode=id)

		# Setup tweepy API
		auth = tweepy.OAuthHandler(cfg['TWITTER_consumer_key'], cfg['TWITTER_consumer_secret'])
		auth.set_access_token(cfg['TWITTER_access_token'], cfg['TWITTER_access_token_secret'])
		api = tweepy.API(auth,wait_on_rate_limit=True, wait_on_rate_limit_notify=True)

		# Get tweet
		_log(f"Attempting to download Tweet user with ID {id}...")

		# try
		_break = False
		attempts = 1
		while _break == False:
			try:
				__tweet = api.get_user(id)
				_break = True
			except:
				wait_for_download()
				attempts += 1
				_log(f"Debug warning: Tweet download attempt failed. Attempt number {attempts} commences.")
				if attempts == cfg["max_attempts"]+1: _break = True

		_json = __tweet._json

		# save json
		with open(json_path, 'w+') as cache_file:
			json.dump(_json, cache_file)

		return(_json)



class YouTubeVideo():
	pass



def part_emoji(text):
	""" Returns the part of emojis in a text string """

	total_len = len(text)
	if total_len == 0:
		warnings.warn("length of string analyzed for emojis is 0", Warning)
		return(0)
	else:
		num_ascii = len(clean_text(text, strip_emoji=True, no_punc=False, no_links=False, no_hash=False, no_digits=False, no_at=False, expand_contractions=False, strip_spaces=False))
		num_emoji = len(get_emojis(text, return_choice="list"))
		return(num_emoji/total_len)





## Functions below here are temporary and can be deleted


def __temp_clean_tweet_caches():
	""" Only for cleaning up erroneously downloaded JSON data """
	i = 0
	bar=progressbar.ProgressBar()
	for path in listdir_nohidden("/Users/kallewesterling/Dropbox/dev/instagram-hashtags/instagramanalysis/__cache__/__tweets/"):
		i+=1
		bar.update()
		with open(path, 'r') as cache_file:
			data = json.load(cache_file)

			if 'id_str' in data: del(data['id_str'])




			if 'retweeted_status' in data and isinstance(data['retweeted_status'], dict):
				print("Found one!")
				# clean tweet here
				retweeted_status_id = data['retweeted_status']['id']
				del(data['retweeted_status'])
				data['retweeted_status'] = retweeted_status_id

				# save json
				with open(path, 'w+') as cache_file:
					json.dump(data, cache_file)

			if 'quoted_status' in data and isinstance(data['quoted_status'], dict):
				print("Found a quoted one!")
				del(data['quoted_status'])

				# save json
				with open(path, 'w+') as cache_file:
					json.dump(data, cache_file)

	bar.finish()




def __temp_clean_post_caches():
	""" Only for cleaning up erroneously downloaded JSON data """
	i = 0
	kb_saved = 0
	files = listdir_nohidden("/Users/kallewesterling/Dropbox/dev/instagram-hashtags/instagramanalysis/__cache__/__posts/")
	bar=progressbar.ProgressBar(max_value=len(files))
	for path in files:
		i+=1
		bar.update(i)
		with open(path, 'r') as cache_file:
			data = json.load(cache_file)
			if data is not None and len(data) > 2:
				_before = len(str(data))

				data = _clean_post(data)

				_after = len(str(data))

				kb_saved += _before - _after

				#to_file
				elements = path.split("/")
				elements[-2] += "-clean"
				to_file = "/".join(elements)

				# save json
				with open(to_file, 'w+') as cache_file:
					json.dump(data, cache_file)

	print(kb_saved, "kb saved.")
	bar.finish()



def _clean_post(data):
	if 'gating_info' in data: del(data['gating_info'])
	if 'is_video' in data: del(data['is_video'])
	if 'should_log_client_event' in data: del(data['should_log_client_event'])
	if 'tracking_token' in data: del(data['tracking_token'])
	if 'viewer_has_liked' in data: del(data['viewer_has_liked'])
	if 'viewer_has_saved' in data: del(data['viewer_has_saved'])
	if 'viewer_has_saved_to_collection' in data: del(data['viewer_has_saved_to_collection'])
	if 'viewer_in_photo_of_you	' in data: del(data['viewer_in_photo_of_you	'])
	if 'viewer_can_reshare' in data: del(data['viewer_can_reshare'])

	data['caption'] = ""
	if 'edge_media_to_caption' in data and len(data['edge_media_to_caption']['edges']) > 0:
		data['caption'] = data['edge_media_to_caption']['edges'][0]['node']['text']
		del(data['edge_media_to_caption'])

	if 'owner' in data and isinstance(data['owner'], dict):
		owner_username = data['owner']['username']
		is_private = data['owner']['is_private']
		del(data['owner'])
		data['owner'] = owner_username
		data['owner_is_private'] = is_private

	data["comments"] = []
	if 'edge_media_to_comment' in data and isinstance(data['edge_media_to_comment'], dict):
		data["num_comments"] = data['edge_media_to_comment']['count']
		for edge in data['edge_media_to_comment']['edges']:
			data['comments'].append({
				'created_at': edge['node']['created_at'],
				'text': edge['node']['text'],
				'owner': edge['node']['owner']['username'],
				'num_liked_by': edge['node']['edge_liked_by']['count']
			})
		del(data['edge_media_to_comment'])

	data['likes'] = []
	if 'edge_media_preview_like' in data:
		data["num_likes"] = data['edge_media_preview_like']['count']
		# del(data['edge_media_preview_like']['count'])
		for edge in data['edge_media_preview_like']['edges']:
			data['likes'].append(edge['node']['username'])
		del(data['edge_media_preview_like'])

	data["tagged"] = []
	if 'edge_media_to_tagged_user' in data:
		for edge in data['edge_media_to_tagged_user']['edges']:
			data['tagged'].append({
				'username': edge['node']['user']['username'],
				'x': edge['node']['x'],
				'y': edge['node']['y'],
			})
		del(data['edge_media_to_tagged_user'])

	data["sponsor_user"] = []
	if 'edge_media_to_sponsor_user' in data:
		for edge in data['edge_media_to_sponsor_user']['edges']:
			data['sponsor_user'].append({
				'username': edge['node']['sponsor']['username']
			})
		del(data['edge_media_to_sponsor_user'])

	if 'edge_web_media_to_related_media' in data:
		if len(data['edge_web_media_to_related_media']['edges']) > 0:
			print("Web media:", data['edge_web_media_to_related_media']['edges'])
		else:
			del(data['edge_web_media_to_related_media'])

	if 'display_resources' in data:
		del(data['display_resources'])

	return(data)
	
	
	

def generate_ngrams(s, n):
	# Function by Albert Au Yeung, albertauyeung.com/post/generating-ngrams-python/
	s = s.lower()
	s = re.sub(r'[^a-zA-Z0-9\s]', ' ', s)
	tokens = [token for token in s.split(" ") if token != ""]
	ngrams = zip(*[tokens[i:] for i in range(n)])
	return [" ".join(ngram) for ngram in ngrams]
	
	
def check_for_new_posts(username=None, return_val='bool'):
	if not username: raise SyntaxError("You must provide a username.")
	if return_val not in ["bool", "list"]: raise SyntaxError("You must provide a valid `return_val`, either bool or list.")
	
	user = InstagramUser(username)
	
	# return()
	if return_val is "bool": new_content = False
	elif return_val is "list": new_content = []
	
	for post in user._raw['edge_owner_to_timeline_media']['edges']:
		if post['node']['shortcode'] is not None:
			path = get_json_path(type='post', shortcode=post['node']['shortcode'])
			try:
				with open(path, "r") as f:
					contents = f.read()
					# print(f"{post['node']['shortcode']} ({path}) was already downloaded.")
			except:
				if return_val is "bool": new_content = True
				elif return_val is "list": new_content.append(post['node']['shortcode'])
				# print(f"{post['node']['shortcode']} was new!")
	return(new_content)


def save_new_posts(username=None, dataset_path=cfg['users_datasets']):
	if not username: raise SyntaxError("You must provide a username.")
	if not dataset_path: raise SyntaxError("You must provide a dataset_path (a path to where user folders are located).")

	dataset_path = Path(dataset_path)
	new_posts = check_for_new_posts(username=username, return_val='list')
	if len(new_posts) > 0:
		now = dt.now()
		fp = f"{dataset_path}/{username}/feed/_{now.year}_{now.month}_{now.day}-posts-{now.second}"
		with open(fp, "w+") as f:
			f.write("\n".join(new_posts))
			# print(f"New shortcodes written to {fp}.")
		for shortcode in new_posts:
			post = InstagramPost(shortcode)
			# print(f"Downloaded post {shortcode}.")
	else:
		print("No new posts found")

def consolidate_shortcode_files(dataset_path=None, consolidated_filename="_consolidated_shortcodes"):
	if not dataset_path: raise SyntaxError("You must provide a dataset_path (a path to where user folders are located).")

	shortcodes = get_shortcodes_from_path(dataset_path)
	dataset_path = Path(dataset_path)
	
	import shutil
	shutil.rmtree(dataset_path, ignore_errors=True) # Remove the directory
	dataset_path.mkdir(parents=True, exist_ok=True) # Create the directory again
	
	# Create a consolidated file
	with open(f"{dataset_path}/{consolidated_filename}", "w+") as f:
		if shortcodes is not None: f.write("\n".join(shortcodes))
		else: 
			f.write("")
			print(f"The dataset path {dataset_path} contained no shortcodes. Consequently the consolidated file will be empty")
	return(None) # this should probably change
	
def check_posts(username=None, return_val='total'):
	_get_instagram_data(type="user", shortcode=username, force_download=True)
	user = InstagramUser(username)
	if return_val == "total":
		return(user.total_posts)
	elif return_val == "recent":
		_ = []
		if user._raw is None:
			return([])
		elif user._raw['edge_owner_to_timeline_media']['edges'] is None:
			return([])
		else:
			for post in user._raw['edge_owner_to_timeline_media']['edges']:
				if post['node']['shortcode'] is not None:
					path = get_json_path(type='post', shortcode=post['node']['shortcode'])
					try:
						with open(path, "r") as f: contents = f.read()
					except:
						_log(f"New post found: {post['node']['shortcode']}", 0)
						_.append(post['node']['shortcode'])
			if len(_) > 0:
				now = dt.now()
				fp = f"{cfg['users_datasets']}/{username}/feed/_{now.year}_{now.month}_{now.day}-posts-{now.second}"
				with open(fp, "w+") as f:
					f.write("\n".join(_))
					_log(f"New shortcodes written to {fp}.", 0)
			return(_)
			
			
def download_photo(shortcode=None, save_path="./", filename=None):
	'''
	Returns: 
		- filename if successful download
	'''
	if shortcode == None: raise SyntaxError("You must provide a shortcode for the post you want downloaded.")

	p = Path(save_path)
	p.mkdir(parents=True, exist_ok=True)
		
	if filename == None: filename = f'{shortcode}.png'
	
	filename = p / filename
	
	if filename.exists():
		pass # File already exists. We could do something else here but we just exit for now
	else:
		post = _get_instagram_data(type='post', shortcode=shortcode, force_download=True)

		wait_for_download()
	
		response = requests.get(post['display_url'], stream=True)
		with open(filename, 'wb') as out_file:
			shutil.copyfileobj(response.raw, out_file)
		del(response)
	
		wait_for_download()
	
	return(filename)
	
	
def get_hashtags_in_cache():
	""" Returns a list of all the hashtags available in the cache """
	_list = [Path(dir).name for dir in listdir_nohidden(cfg['hashtags_datasets'])]
	return(sorted(_list))


def get_hashtag_cache_dir(hashtag=None):
	if hashtag is None: raise SyntaxError("You must provide a hashtag for which you are requesting the cache directory.")
	return(cfg["hashtags_datasets"] / hashtag)


def scrape_shortcodes(hashtag=None, user=None, scrolls=10, to_file=None, existing_browser=None, start_in_place=False, max_repeated_cache=4, max_repeated_scrape=4, force_cache=False, force_repeat=False):
	""" Scrapes shortcodes from any Instagram page for either a provided hashtag or a user """

	if start_in_place == False and hashtag == None and user == None: raise SyntaxError("You must provide either a hashtag or a user that you want scraped.")
	elif start_in_place == True and (hashtag is not None or user is not None): raise RuntimeWarning("You passed a hashtag or a user but also set start_in_place to True. Hashtag and/or user will be ignored and your current browser will be used instead.")

	if start_in_place is True and existing_browser is None: raise RuntimeError("If start_in_place is set to True, an existing_browser must be passed to the function.")

	if to_file is not None:
		if Path(to_file).name[0:1] is not "_": print("Warning: Shortcode files should start with an underscore (_) to ensure that the module works appropriately.")

		# First make sure directory exists
		_path = os.path.split(to_file)[0]
		if not Path(_path).exists():
			file = Path(_path)
			file.mkdir(parents=True, exist_ok=True)


	if existing_browser is None:
		# Set up browser
		browser = webdriver.Firefox()
		browser.set_window_size(100, 1000)
	else:
		# We were provided an existing browser window (this is good when you loop over a number of items you want scraped)
		browser = existing_browser

	# If we are not passed "start_in_place," go to correct page. Otherwise, we can just continue where the passed existing_browser is 
	if not start_in_place:
		if hashtag is not None: browser.get(url=f"http://www.instagram.com/explore/tags/{hashtag}/")
		elif user is not None: browser.get(url=f"http://www.instagram.com/{user}/")
	elif start_in_place:
		g = re.search("(\S+) hashtag", browser.title)
		hashtag = g.groups()[0][1:]

	_found, _latest = [], []
	_latest_counter, _cache_compare = 0, 0
	printed_msg_latest, printed_msg_compare = False, False

	if hashtag is not None:
		__cached_shortcodes = get_shortcodes_from_hashtags(hashtags=hashtag)
	elif user is not None:
		__cached_shortcodes = get_shortcodes_from_users(users=user)

	bar = progressbar.ProgressBar(max_value=scrolls).start()

	for i in range(0, scrolls):
		if not force_repeat and (_latest_counter >= max_repeated_scrape):
				if not printed_msg_latest:
					print("Encountered too many repetitive shortodes. Will not scrape this round...")
					printed_msg_latest = True
				continue # This tests for new posts for four times, then stops downloading more posts
		if not force_cache and (_cache_compare >= max_repeated_cache):
				if not printed_msg_compare:
					print("Encountered too many shortodes that were already in the cache. Will not scrape this round...")
					printed_msg_compare = True
				continue # This tests for new posts for four times, then stops downloading more posts
		bar.update(i)
		body_text = browser.find_element_by_tag_name(name="body").text
		body_text = body_text.lower()
		search = body_text.find("failed to load")
		if search > 0:
			wait = round(random.uniform(cfg['downloads_wait_min']*10, cfg['downloads_wait_max']*10), 2)
			print(f"Waiting {wait} because of a hold-up.") # this should be removed in production
			time.sleep(wait)
		else:
			wait = round(random.uniform(cfg['downloads_wait_min'], cfg['downloads_wait_max']), 2)
			time.sleep(wait)

		elems = browser.find_elements_by_class_name(name="Nnq7C")
		if len(elems) == 0:
			print("Warning: Found no posts.")
			continue
		for elem in elems:
			html = elem.get_attribute("innerHTML")
			g = re.findall("\/p\/(\S+)\/", html)
			_found.extend(g)

		browser.execute_script(f"window.scrollBy(0, -100)") # This helps if the page gets stuck
		browser.execute_script(f"window.scrollBy(0, 1000)")

		if not force_cache and (check_latest_against_existing_shortcodes(g, __cached_shortcodes) == 0):
				_cache_compare += 1
				print(f"All of the latest posts found are already in cache ({_cache_compare}/{max_repeated_cache}).")
		elif not force_cache:
			_cache_compare = 0 # reset since we found some new stuff!

		if not force_repeat and (_latest == g):
			# Same shortcodes as the last scrape... Trying a few more times. But don't print anything because this will happen pretty frequently
			_latest_counter += 1
			print(f"All of the latest posts found were already scraped ({_latest_counter}/{max_repeated_scrape}).")
		elif not force_repeat:
			_latest = g
			_latest_counter = 0 # reset since we found some new stuff!

	bar.finish()

	_found = list(set(_found))

	if to_file is not None:
		shortcode_file = Path(to_file)
		with open(shortcode_file, "w+") as f:
			f.write("\n".join(_found))
			print(f"{len(_found)} shortcodes written to file {shortcode_file}.")
		return_val = True
	else:
		return_val = _found

	if existing_browser is None: browser.quit()

	return(return_val)


def check_latest_against_existing_shortcodes(_shortcode_list, __cached_shortcodes):
	return(len(set(_shortcode_list)-set(__cached_shortcodes)))
	
	



### INSTAGRAMSPIDER


class InstagramSpider():
	
	def __init__(self, login=True):
		self._window = webdriver.Firefox()
		self._window.set_window_size(100, 1000)

		if login:
			# Login to Instagram
			self._window.get("https://www.instagram.com/accounts/login/")
			login = "kallewesterling" # login = input("Login: ")
			password = "rFj7XYDZ" # password = input("Password: ")

			time.sleep(1)

			login_class = self._window.find_elements_by_class_name("_9nyy2")[0].get_attribute("for")
			_login = self._window.find_element_by_id(id_=login_class)
			pw_class = self._window.find_elements_by_class_name("_9nyy2")[1].get_attribute("for")
			_pw = self._window.find_element_by_id(id_=pw_class)

			_login.click()
			_login.send_keys(login)

			_pw.click()
			_pw.send_keys(password)

			for elem in self._window.find_elements_by_class_name("_0mzm-"):
				if elem.text == "Log In":
					elem.click()

			time.sleep(5)

			try:
				self._window.find_element_by_class_name('HoLwm').click() # Click "Not Now"
			except:
				print("Warning: Dialog might be still open. Dismiss manually.")
	
	def search(self, hashtag=None, user=None):
		if hashtag is not None and user is not None: raise RuntimeError("Cannot accept both user and hashtag at once.")
		
		if hashtag is not None: self._window.get(f"https://www.instagram.com/explore/tags/{hashtag}/")
		elif user is not None: self._window.get(f"https://www.instagram.com/{user}/")

	def get_info(self):
		_hashtag, _user = None, None
		try:
			g = re.search("(\S+) hashtag", self._window.title)
			_hashtag = g.groups()[0][1:]
		except:
			pass
			
		try:
			g = re.search("(.*) \((.*)\)", self._window.title)
			_user = g.groups()[1][1:]
		except:
			pass
			
			
			
		return({
			'hashtag': _hashtag,
			'user': _user,
		})

	def get_number_of_posts(self, hashtag=None, user=None):
		
		if hashtag is not None and user is not None: raise RuntimeError("Cannot accept both user and hashtag at once.")

		if hashtag is not None:
			on_page = False
			try:
				g = re.search("(\S+) hashtag", self._window.title)
				_hashtag = g.groups()[0][1:]
				if _hashtag == hashtag: on_page = True # we are on the hashtag page!
			except:
				pass
			if not on_page: self._window.get(f"http://www.instagram.com/explore/tags/{hashtag}/")
			try:
				elem = self._window.find_element_by_class_name(name="g47SY")
				num_posts = int(elem.text.replace(',', ''))
			except:
				num_posts = 0
			return(num_posts)
		elif user is not None:
			on_page = False
			try:
				g = re.search("(.*) \((.*)\)", self._window.title)
				_user = g.groups()[1][1:]
				if _user == user: on_page = True # we are on the hashtag page!
			except:
				pass
			if not on_page: self._window.get(f"http://www.instagram.com/{user}/")
			else: print("We are on user page already")
			try:
				elem = self._window.find_element_by_class_name(name="g47SY")
				num_posts = int(elem.text.replace(',', ''))
			except:
				num_posts = 0
			return(num_posts)
		else:
			hashtag_page, user_page = False, False
			try:
				g = re.search("(\S+) hashtag", self._window.title)
				_hashtag = g.groups()[0][1:]
				hashtag_page = True
			except:
				try:
					g = re.search("(.*) \((.*)\)", self._window.title)
					_hashtag = g.groups()[0][1:]
					user_page = True
				except:
					raise RuntimeError(f"Cannot find out what kind of page the browser is currently at.")

			if hashtag_page:
				try:
					elem = self._window.find_element_by_class_name(name="g47SY")
					num_posts = int(elem.text.replace(',', ''))
				except:
					num_posts = 0
				return(num_posts)

			if user_page:
				try:
					elem = self._window.find_element_by_class_name(name="g47SY")
					num_posts = int(elem.text.replace(',', ''))
				except:
					num_posts = 0
				return(num_posts)


	def lazy_get_number_of_posts(self):
		try:
			elem = self._window.find_element_by_class_name(name="g47SY")
			num_posts = int(elem.text.replace(',', ''))
		except:
			num_posts = None
		return(num_posts)
	
	
	def scroll(self, amount):
		self._window.execute_script(f"window.scrollBy(0, -100)") # This helps if the page gets stuck
		self._window.execute_script(f"window.scrollBy(0, {amount})")


	def scrape_shortcodes(self, strict=False):
		elems = self._window.find_elements_by_class_name(name="Nnq7C")
		_g = []
		errors = 0
		for elem in elems:
			try:
				html = elem.get_attribute("innerHTML")
				g = re.findall("\/p\/(\S+)\/", html)
				_g.extend(g)
			except Exception as e:
				if len(re.findall("(The element reference) (.*) (is stale)", str(e))) > 0: errors += 1
		if errors > 0 and strict: print(f"Errors: {errors}.") # can be logged
		return(list(set(_g)))

	def shortcodes_append_file(self, filename="", shortcodes=[]):
		existing_shortcodes = []
		if len(shortcodes) <= 0:
			shortcodes = self.scrape_shortcodes(strict=False)
		existing_shortcodes = set(get_shortcodes_from_path(os.path.dirname(filename)))
		new_shortcodes = list(set(shortcodes) - existing_shortcodes)
		if len(new_shortcodes) > 0:
			for p in filename.parents:
				if not p.exists(): p.mkdir(parents=True)
			with open(Path(filename), "a+") as f:
				f.write("\n".join(new_shortcodes)+"\n")
		return({
			'appended_file': filename,
			'appended_shortcodes': new_shortcodes,
			'appended_shortcodes_int': len(new_shortcodes),
		})
		
	def check_for_halt(self):
		body_text = self._window.find_element_by_tag_name(name="body").text
		body_text = body_text.lower()
		search = body_text.find("failed to load")
		if search > 0:
			return(True)
		else:
			return(False)






class InstagramDatasetSample():
	
	def __init__(self, dataset, k):
		self.sample_shortcodes = random.choices(dataset.shortcodes, k=k)
		self.sample_posts = random.choices(dataset.posts, k=k)
		
		
		

if __name__ == "__main__":
	print(__author__)
	print(__version__)
elif __name__ == "instagram": # We're importing!
	if cfg['level_reporting'] >= 10: print(f"Running Instagram module version {__version__}.")
