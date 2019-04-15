"""
Copyright (C) 2014 Emmanuel Noutahi
Please don't change the original Copyright when you modify the program

"""
from urllib.request import Request, urlopen
import sqlite3 as lite
import os.path, sys
from pprint import pprint
from discord_webhook import DiscordWebhook, DiscordEmbed
import json
import requests

with open("parameters.json", 'r') as json_data_file:
    config = json.load(json_data_file)

BASE_DIR = config['system']['base']
DATA_DIR = config['system']['data']
DATABASE_NAME = config['database']['name']
MANGALIST = config['database']['list']
MANGA_TABLE = config['database']['table']
discordUrl = config['discord']['url']

API_BASE = "https://www.mangaeden.com/api/"
IMG_BASE = "http://cdn.mangaeden.com/mangasimg/"


def discordNotif(update_infos, mails=[]):

	message="These Mangas have been updated :"
	embed = DiscordEmbed(title="New Manga", description=message, color=0e9319)
	for info in update_infos:
		mangaName=info[0]
		chapter=info[1]
		embed.add_embed_field(name=mangaName, value=chapter)
		webhook = DiscordWebhook(url=discordUrl)
		webhook.add_embed(embed)
		webhook.execute()
		del webhook

def update_manga_list():
	'''Update List of accessible manga and save to DATA_DIR, this take some time'''
	dir_check = os.path.dirname(DATA_DIR)
	if not os.path.exists(dir_check):
		os.makedirs(DATA_DIR)

	jsonfile=DATA_DIR+MANGALIST
	manga_list = getJson(API_BASE+"list/0/")
	with open(jsonfile, 'w+') as file:
		json.dump(manga_list, file)
	
	con = lite.connect(DATA_DIR+DATABASE_NAME)
	with con:
		cur = con.cursor()
		if( not table_exists(table_name=MANGA_TABLE, cur=cur)):
			cur.execute("CREATE TABLE "+MANGA_TABLE+"(UniqId TEXT primary key not null, Title TEXT , Author TEXT, Artist TEXT, Summary TEXT, Years INT, Image TEXT, Last_Chapter_Date datetime, Last_Chapter INT, Tot_Chapter INT, Follow BOOLEAN, Chap_Dir TEXT)")
			con.commit()
		

def update_manga(manga_id=None, get_current_chap=0):
	'''Update the list of manga i'm following and download the latest release if possible.
	with get_current_chap,  get the current chapter and save to a directory named 'latest
	with notify, send notification using a function '''
	con= lite.connect(DATA_DIR+DATABASE_NAME)
	manga_updated=[]
	with con:
		cur=con.cursor()
		sql_req = "SELECT UniqId, Last_Chapter, Chap_Dir, Title, Tot_Chapter FROM "+MANGA_TABLE+" WHERE Follow=%i"%True
		if manga_id:
			sql_req = sql_req+"and UniqId=%s"%manga_id
		cur.execute(sql_req)
		manga_resp = cur.fetchall()
		for manga in manga_resp:
			cur_last_chapter = manga[1]	
			chapter_id = get_manga_chapter_id(manga[0], chapter=manga[1]+1, get_latest_chapters_id=True)

			for chap_num, chap_id in list(chapter_id.items()):
				manga_dir = manga[2]+"%i/"%(chap_num)
				success = save_chapter_to(manga_dir, get_chapter_info(chap_id))
				manga[4] += 1
				cur_last_chapter = chap_num

			cur.execute("UPDATE "+MANGA_TABLE+" SET Last_Chapter=%i, Tot_Chapter=%i, Last_Chapter_Date = (datetime('now','localtime')) WHERE UniqId='%s'" %(cur_last_chapter, manga[4], manga[0]))
			manga_updated.append([manga[3], cur_last_chapter, manga[2]])

			if(get_current_chap==1 and not os.path.exists(manga[2]+"%i/"%(manga[1]))):
				save_chapter_to(manga[2]+"%i/"%(manga[1]), get_chapter_info(get_manga_chapter_id(manga[0], chapter=manga[1])))

		con.commit()
	if(manga_updated):
		discordNotif(manga_updated)


def download_manga(manga_id, manga_base_dir, chap_start=1, chap_end=None):
	'''download manga with id 'manga_id' from chap_start to chap_end and save to manga_base_dir'''
	success=True
	assert (chap_start>0), "Chapter start should be a positif integer!"
	while(success and ((chap_end and chap_start and chap_start<chap_end) or (not chap_end))):
		chapter_id = get_manga_chapter_id(manga_id, chapter=chap_start)
		
		if(not chap_start):
			chap_d = "latest/"
		else:
			chap_d = "%i/"%chap_start
			chap_start+=1
		success=save_chapter_to(manga_base_dir+chap_d, get_chapter_info(chapter_id))
		print("\rchapter -%s- downloaded"%chap_d, end=' ')

	if(success):
		print("\nChapters Downloaded into %s !"%manga_base_dir)


def get_manga_info(manga_id):
	'''return manga info in a tuple (for insertion in database)'''
	manga_json = getJson(API_BASE+"manga/"+manga_id)
	title = manga_json["title"]
	artist = manga_json["artist"]
	author = manga_json["author"]
	tot_chapter = manga_json["chapters_len"]
	last_chapter = 0
	chapters = manga_json["chapters"]
	if(len(chapters)>0):
		last_chapter=chapters[0][0]
	image = IMG_BASE+manga_json["image"]
	last_update = int(manga_json["last_chapter_date"])
	years = 0
	if(manga_json["released"]):
		years=manga_json["released"]
	summary = manga_json["description"]

	manga = (manga_id, title, author, artist, summary, int(years), image, last_update, last_chapter, tot_chapter)
	return manga


def search_manga(manga_name, bestmatch=True):
	'''search manga  and return only bestmatch or all match'''
	matching_manga = []
	max_hit_pos =- 1
	max_hit =- 1
	with open(DATA_DIR+MANGALIST) as json_data:
		manga_json = json.load(json_data)
		manga_list = manga_json["manga"]
		i = 0
		for manga in manga_list:
			if (manga_name.lower() in manga["a"].lower()) or  (manga_name.lower() in manga["t"].lower()):
				matching_manga.append(manga)
				if(manga["h"] > max_hit):
					max_hit_pos = i
					max_hit = manga["h"]
				i+=1

	if(max_hit>=0 and bestmatch): return [matching_manga[max_hit_pos]]
	return matching_manga


def add_manga(manga_info=None, manga_id=None):
	'''add_manga to database'''
	con= lite.connect(DATA_DIR+DATABASE_NAME)
	if manga_info is None and manga_id is not None:
		manga_info = get_manga_info(manga_id)

	chap_dir = BASE_DIR+manga_info[1]+"/"
	if not os.path.exists(chap_dir):
		os.makedirs(chap_dir)
	with con:
		cur = con.cursor()
		if( not table_exists(table_name=MANGA_TABLE, cur=cur)):
			cur.execute("CREATE TABLE "+MANGA_TABLE+"(UniqId TEXT primary key not null, Title TEXT , Author TEXT, Artist TEXT, Summary TEXT, Years INT, Image TEXT, Last_Chapter_Date datetime, Last_Chapter INT, Tot_Chapter INT, Follow BOOLEAN, Chap_Dir TEXT)")
		cur.execute("INSERT OR IGNORE INTO "+MANGA_TABLE+" VALUES(?,?,?,?,?,?,?, (SELECT datetime(?, 'unixepoch')),?,?,?,?)", manga_info+(True, chap_dir,))
		con.commit()


def get_manga_chapter_id(manga_id, chapter=None, get_latest_chapters_id=False):
	'''Get manga chapter id '''
	manga_json = getJson(API_BASE+"manga/"+manga_id)
	chapter_id = None
	latest_chapters_id = {}
	if(manga_json):
		chapters = manga_json["chapters"]
		if chapter is None:
			try:
				chapter = chapters[0][0]
			except:
				chapter = 0
				print("Chapter not found!!! ")

		for chapt in chapters:
			
			if (chapter <= chapt[0]):
				latest_chapters_id[chapt[0]] = chapt[3]

			if chapter == chapt[0]:
				chapter_id = chapt[3]
				break
	return chapter_id if not get_latest_chapters_id else latest_chapters_id


def get_chapter_info(chapter_id):
	'''Get chapter informations (images) in json format'''
	chapter_json = None
	if(chapter_id is not None):
		chapter_json = getJson(API_BASE+"chapter/"+chapter_id)

	return chapter_json


def save_chapter_to(dir_name, chapter_json):
	'''Save the chapter into dir_name'''
	success = False
	if(chapter_json):
		if(dir_name is None):
			dir_name = "Downloaded"
		if not os.path.exists(dir_name):# and os.access(dir_name, os.W_OK):
			os.makedirs(dir_name)
		images = chapter_json["images"]
		for image in images:
			ext = image[1].split('.')[1]
			with open(dir_name+str(image[0])+"."+ext, "w+") as pic:
				pic.write(urlopen(IMG_BASE+image[1]).read())
			success = True
	return success


def delete_from_database(manga_id):
	'''delete manga from database'''
	con = lite.connect(DATA_DIR+DATABASE_NAME)
	with con:
		cur = con.cursor()
		cur.execute("DELETE FROM "+MANGA_TABLE+" WHERE UniqId = ? ", (manga_id,))
		con.commit()


def table_exists(table_name=None, cur=None ):
	'''check if table exists'''
	sql = "SELECT * FROM sqlite_master WHERE name ='%s' and type='table'"%table_name 
	cur.execute(sql)
	response = cur.fetchall()
	return True if len(response)>0 else False


def update_follow_manga(manga_id, following):
	'''Do not update this manga anymore'''
	con = lite.connect(DATA_DIR+DATABASE_NAME)
	with con:
		cur = con.cursor()
		cur.execute("UPDATE "+MANGA_TABLE+"  SET Follow= ? WHERE UniqId = ?", (following, manga_id,))
		con.commit()


def getJson(link):
	'''get json from link'''
	headers = {"Accept": "application/json"}
	request = Request(link, headers=headers)
	response=urlopen(request).read()
	return json.loads(response)


def add_manga_list(my_list, bestmatch=True):
	'''add this list of manga to my database'''
	i=0
	tot = len(my_list)
	for manga_name in my_list:
		i += 1
		search_res = search_manga(manga_name, bestmatch=bestmatch)
		if(search_res):
			add_manga(manga_id=search_res[0]["i"])
			print("\r{0} Added - ({1} %)".format(search_res[0]['t'], (i*100.0/tot)), end=' ') 
	print("\n")


def drop_table():
	'''Drop the table containing manga'''
	con=lite.connect(DATA_DIR+DATABASE_NAME)
	with con:
		cur = con.cursor()
		cur.execute("DROP TABLE IF EXISTS "+MANGA_TABLE)
		con.commit()


def exists_in_table(manga_id):
	con=lite.connect(DATA_DIR+DATABASE_NAME)
	with con:
		cur = con.cursor()
		if(table_exists(MANGA_TABLE, cur)):
			cur.execute("SELECT  Follow, Title FROM "+MANGA_TABLE +" WHERE UniqId = ?",(manga_id,))
			follow = cur.fetchone()
			return (follow is not None, follow)
	return (False, False)


def current_table():
	con=lite.connect(DATA_DIR+DATABASE_NAME)
	result = None
	with con:
		cur = con.cursor()
		if(table_exists(MANGA_TABLE, cur)):
			cur.execute("SELECT  Title,  Author, Years, Last_Chapter, Follow, strftime('%Y:%m:%d', Last_Chapter_Date) FROM "+MANGA_TABLE)
			result = cur.fetchall()
			return result
	return result