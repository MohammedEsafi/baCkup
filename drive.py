from __future__ import print_function
import pickle
import os.path
import json
import datetime
import hashlib
import io
import sys
from tqdm import tqdm
from googleapiclient.discovery import build
from googleapiclient.discovery import MediaFileUpload
from googleapiclient.http import MediaIoBaseDownload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

class formats: 
	reset='\033[0m'
	bold='\033[01m'
	disable='\033[02m'
	italic='\033[03m'
	underline='\033[04m'
	red='\033[31m'
	green='\033[32m'
	yellow='\033[33m'
	light_yellow='\033[93m'

usage = '''drive. keep your files in sync
usage: python drive.py [options] backup    sync your files to google drive.
       python drive.py [options] restore   restore all folders / files from Cloud.
       python drive.py init                configure drive
       python drive.py -h --help           show this help message.
       python drive.py --version           show version.
options:
       -f --force       force every question asked to be answered with "Yes".
       -s --silent      silent or quiet mode. don't show progress bar
'''

SCOPES = ['https://www.googleapis.com/auth/drive']
not_exist = list()

def opt(argv):
	options = ['backup', 'restore', '--help', '--version', '--force', '-h', '--silent', '-s', 'init']
	args = dict()
	for item in options:
		if item in argv:
			args[item] = True
		else:
			args[item] = False
	return (args)

def save(path, content):
	with open(path, 'w+') as file:
		json.dump(content, file, indent=4)

def backup(service, parent_id, contents_list: list, cloudSettings=None, stripe=None):
	if len(contents_list) == 0:
		return
	dirname = os.path.dirname(contents_list[0])
	lists = service.files().list(q="'{}' in parents and trashed=false and not name contains 'cloudSettings.json'".format(parent_id), \
			spaces='drive', fields="nextPageToken, files(id, name, md5Checksum)").execute()
	files = lists.get('files', [])

	for file in files:
		if not any(file['name'] == (elem.split('/'))[-1] for elem in contents_list):
			service.files().delete(fileId=file['id']).execute()
			if cloudSettings:
				cloudSettings['source_paths'].pop(file['id'])

	for item in contents_list:
		file_metadata = {
			'name': os.path.basename(item),
			'parents': [parent_id]
		}
		if not os.path.exists(item):
			if cloudSettings:
				global not_exist
				not_exist.append(item)
		elif os.path.isdir(item):
			file_metadata['mimeType'] = 'application/vnd.google-apps.folder'
			node = next((file for file in files if file['name'] == file_metadata['name']), False)
			if not node:
				folder_id = service.files().create(body=file_metadata, fields='id').execute().get('id')
			else:
				folder_id = node['id']
			if cloudSettings:
					cloudSettings['source_paths'][folder_id] = item
			backup(service, folder_id, list(os.path.join(item, child) for child in os.listdir(item)), stripe=stripe)		
		else:
			media = MediaFileUpload(item, resumable=True) if os.stat(item).st_size != 0 else None
			node = next((file for file in files if file['name'] == file_metadata['name']), False)
			if not node:
				file_id = service.files().create(body=file_metadata, media_body=media, fields='id').execute().get('id')
			else:
				file_id = node['id']
				with open(item, 'rb') as file:
					if hashlib.md5(file.read()).hexdigest() != node['md5Checksum']:
						service.files().update(fileId=file_id, media_body=media).execute()
			if cloudSettings:
					cloudSettings['source_paths'][file_id] = item
			if stripe:
				stripe.update(1)

def downloader(service, Id, path):
	request = service.files().get_media(fileId=Id)
	memory = io.BytesIO()
	downloader = MediaIoBaseDownload(memory, request)
	done = False
	while done is False:
		status, done = downloader.next_chunk()
	with io.open(path, 'wb+') as file:
		memory.seek(0)
		file.write(memory.read())

def restore(service, parent_id, parent_path=None, source_paths=None, stripe=None):
	lists = service.files().list(q="'{}' in parents and trashed=false".format(parent_id), \
			spaces='drive', fields="nextPageToken, files(id, name, mimeType, md5Checksum)").execute()
	files = lists.get('files', [])

	for item in files:
		if parent_path is None:
			path = source_paths[item['id']]
		else:
			path = os.path.join(parent_path, item['name'])
		if item['mimeType'] == 'application/vnd.google-apps.folder':
			if not os.path.exists(path):
				os.makedirs(path, exist_ok=True)
			restore(service, item['id'], parent_path=path, stripe=stripe)
		else:
			if not os.path.exists(path):
				open(path, 'a').close()
			with open(path, 'rb+') as file:
				if hashlib.md5(file.read()).hexdigest() != item['md5Checksum']:
					downloader(service, item['id'], path)
			if stripe:
				stripe.update(1)

def main():
	# Get the command line args
	argv = sys.argv
	args = opt(argv)

	# --help and -h opt
	if args["--help"] or args["-h"] or (len(argv) - 1 == 0):
		print(usage, end='')
		sys.exit(0)

	# --version opt
	if args["--version"]:
		print('v1.0.0')
		sys.exit(0)

	# If we want to answer baCkup with "yes" for each question
	if args["--force"]:
		__FORCE = True
	else:
		__FORCE = False

	# display progress information as a progress bar
	indent = "{}{}‣ {}".format(formats.bold, formats.green, formats.reset)
	if args['--silent'] or args['-s']:
		bar_format = indent + "{percentage:3.0f}%"
	else:
		bar_format = indent + "{percentage:3.0f}% {bar} {n_fmt}/{total_fmt} items"

	# read .config files
	with open('.config/credentials.json', 'r+') as file:
		credentials = json.load(file)
	with open('.config/cloudSettings.json', 'r+') as file:
		cloudSettings = json.load(file)

	# init
	if args['init']:
		credentials['installed']['client_id'] = input("client_id: ")
		credentials['installed']['client_secret'] = input("client_secret: ")
		cloudSettings['backup_name'] = input("backup_name: (iCloud) ")
		cloudSettings['backup_id'] = input("backup_id: ")
		if cloudSettings['backup_id']:
			cloudSettings['assume'] = False
		
		# Save
		save('.config/cloudSettings.json', cloudSettings)
		save('.config/credentials.json', credentials)
		sys.exit(0)

	if not credentials['installed']['client_id'] or not credentials['installed']['client_secret']:
		print("{}client_id{} and {}client_secret{} not set.".format(formats.italic, formats.reset, formats.italic, formats.reset))
		sys.exit(0)

	creds = None
	# The file .config/token.pickle stores the user's access and refresh tokens, and is
	# created automatically when the authorization flow completes for the first
	# time.
	if os.path.exists('.config/token.pickle'):
		with open('.config/token.pickle', 'rb') as token:
			creds = pickle.load(token)

	# If there are no (valid) credentials available, let the user log in.
	if not creds or not creds.valid:
		if creds and creds.expired and creds.refresh_token:
			creds.refresh(Request())
		else:
			flow = InstalledAppFlow.from_client_secrets_file('.config/credentials.json', SCOPES)
			creds = flow.run_local_server(port=0)
		# Save the credentials for the next run
		with open('.config/token.pickle', 'wb') as token:
			pickle.dump(creds, token)

	service = build('drive', 'v3', credentials=creds)

	# read the ID of the folder where your data is kept ; create if not exist
	if not cloudSettings['backup_id']:
		file_metadata = {
			'name': cloudSettings['backup_name'] if cloudSettings['backup_name'] else 'iCloud',
			'mimeType': 'application/vnd.google-apps.folder'
		}
		results = service.files().create(body=file_metadata, fields='id').execute()
		cloudSettings['backup_id'] = results['id']

	backup_id = cloudSettings['backup_id']

	# read `~/.config.ini` file containing full path of source folders / files to backup
	paths = None
	try:
		with open(os.path.expanduser('~/.config.ini'), 'r') as file:
			paths = file.read().splitlines()
	except IOError:
		pass

	# backup opt
	if args['backup']:
		source_paths = list(os.path.expanduser(item).rstrip('/') for item in paths[1:])

		# count files
		files_count = 0
		for item in source_paths:
			if os.path.isdir(item):
				files_count += sum(len(files) for path, dirs, files in os.walk(item))
			else:
				files_count += 1
		cloudSettings['files_count'] = files_count

		# progress bar
		stripe = tqdm(total=(files_count + 1), ascii=" ▥▥▥▥▥▥▥▥▥", ncols=60, bar_format=bar_format)

		backup(service, backup_id, source_paths, cloudSettings=cloudSettings, stripe=stripe)
		cloudSettings["lastUpload"] = str(datetime.datetime.now())

	# restore opt
	elif args['restore']:
		# for restore, assuming a first time (download cloudSettings.json from drive)
		if cloudSettings['assume'] == False:
			lists = service.files().list(q="'{}' in parents and trashed = false and name = 'cloudSettings.json'".format(backup_id), \
					spaces='drive', fields="nextPageToken, files(id)").execute()
			files = lists.get('files', [])
			cloudSettings['id'] = files[0]['id']
			downloader(service, cloudSettings['id'], '.config/cloudSettings.json')
			with open('.config/cloudSettings.json', 'r+') as file:
				cloudSettings = json.load(file)
			cloudSettings['assume'] = True
			save('.config/cloudSettings.json', cloudSettings)

		# progress bar
		stripe = tqdm(total=cloudSettings['files_count'], ascii=" ▥▥▥▥▥▥▥▥▥", ncols=60, bar_format=bar_format)
		
		restore(service, backup_id, source_paths=dict(cloudSettings['source_paths']), stripe=stripe)
		stripe.close()

	else:
		print(usage, end='')

	# save cloudSettings and upload
	if args['backup']:
		media = MediaFileUpload('.config/cloudSettings.json', resumable=True) if os.stat(item).st_size != 0 else None
		if not cloudSettings['id']:
			file_metadata = {
				'name': 'cloudSettings.json',
				'parents': [backup_id]
			}
			cloudSettings['id'] = service.files().create(body=file_metadata, media_body=media, fields='id').execute().get('id')
		save('.config/cloudSettings.json', cloudSettings)
		service.files().update(fileId=cloudSettings['id'], media_body=media).execute()
		stripe.update(1)
		stripe.close()
		# not exist paths
		global not_exist
		for item in not_exist:
			print("The path {}{}{}{} does not exist, or access denied.".format(formats.italic, formats.yellow, item, formats.reset))

if __name__ == '__main__':
    main()
