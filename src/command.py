import asyncio
import logging
import os
import time

from watchgod import awatch
from watchgod.watcher import Change

from conf import Config, MEDIA_FILE_EXTENSIONS
from decorator import parser_config
from gateway import Gateway
from utils import get_template_name, progress_bar


logging.basicConfig(
    format='%(asctime)s %(levelname)s %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S'
)


class Command:
    def __init__(self):
        self.config = Config()
        self.gateway = Gateway(store=self.config.store, apikey=self.config.apikey)

    def _handle_files_change(self, changes):
        for event_type, pathfile in changes:
            template_name = get_template_name(pathfile)
            current_pathfile = os.path.join(os.getcwd(), template_name)

            if current_pathfile.endswith(('.py', '.yml', '.conf')):
                continue

            if event_type in [Change.added, Change.modified]:
                logging.info(f'[{self.config.env}] {str(event_type)} {template_name}')
                self._push_themplates([template_name])
            elif event_type == Change.deleted:
                logging.info(f'[{self.config.env}] {str(event_type)} {template_name}')
                self._delete_templates([template_name])

    def _push_themplates(self, template_names):
        template_count = len(template_names)
        logging.info(f'[{self.config.env}] Connecting to {self.config.store}')
        logging.info(f'[{self.config.env}] Uploading {template_count} files to theme id {self.config.theme_id}')

        for template_name in progress_bar(
                template_names, prefix=f'[{self.config.env}] Progress:', suffix='Complete', length=50):
            template_name = get_template_name(template_name)
            current_pathfile = os.path.join(os.getcwd(), template_name)

            files = {}
            payload = {
                'name': template_name,
                'content': ''
            }
            if current_pathfile.endswith(('.py', '.yml', '.conf')):
                continue

            if current_pathfile.endswith(tuple(MEDIA_FILE_EXTENSIONS)):
                files = {'file': (template_name, open(current_pathfile, 'rb'))}
            else:
                with open(current_pathfile, 'r') as f:
                    payload['content'] = f.read()
                    f.close()

            response = self.gateway.create_update_template(self.config.theme_id, payload=payload, files=files)
            if not response.ok:
                result = response.json()
                error_msg = f'Can\'t update to theme id #{self.config.theme_id}.'
                if result.get('content'):
                    error_msg = ' '.join(result.get('content', []))
                if result.get('file'):
                    error_msg = ' '.join(result.get('file', []))
                logging.error(f'[{self.config.env}] {template_name} -> {error_msg}')

    def _pull_themplates(self, template_names):
        templates = []
        if template_names:
            for filename in template_names:
                template_name = get_template_name(filename)
                response = self.gateway.get_template(self.config.theme_id, template_name)
                templates.append(response.json())
        else:
            response = self.gateway.get_templates(self.config.theme_id)
            templates = response.json()

        if type(templates) != list:
            logging.info(f'Theme id #{self.config.theme_id} doesn\'t exist in the system.')
            return

        template_count = len(templates)
        logging.info(f'[{self.config.env}] Connecting to {self.config.store}')
        logging.info(f'[{self.config.env}] Pulling {template_count} files from theme id {self.config.theme_id} ')
        current_files = []
        for template in progress_bar(templates, prefix=f'[{self.config.env}] Progress:', suffix='Complete', length=50):
            template_name = str(template['name'])
            current_pathfile = os.path.join(os.getcwd(), template_name)
            current_files.append(current_pathfile.replace('\\', '/'))

            # create directories
            dirs = os.path.dirname(current_pathfile)
            if not os.path.exists(dirs):
                os.makedirs(dirs)

            # write file
            if template['file']:
                response = self.gateway._request("GET", template['file'])
                with open(current_pathfile, "wb") as media_file:
                    media_file.write(response.content)
                    media_file.close()
            else:
                with open(current_pathfile, "w", encoding="utf-8") as template_file:
                    template_file.write(template.get('content'))
                    template_file.close()

            time.sleep(0.08)

    def _delete_templates(self, template_names):
        template_count = len(template_names)
        logging.info(f'[{self.config.env}] Connecting to {self.config.store}')
        logging.info(f'[{self.config.env}] Deleting {template_count} files from theme id {self.config.theme_id}')

        for template_name in progress_bar(
                template_names, prefix=f'[{self.config.env}] Progress:', suffix='Complete', length=50):
            template_name = get_template_name(template_name)
            response = self.gateway.delete_template(self.config.theme_id, template_name)
            if not response.ok:
                result = response.json()
                error_msg = f'Can\'t delete to theme id #{self.config.theme_id}.'
                if result.get('detail'):
                    error_msg = ' '.join(result.get('detail', []))
                logging.error(f'[{self.config.env}] {template_name} -> {error_msg}')

    @parser_config(theme_id_required=False)
    def init(self, parser):
        if parser.name:
            response = self.gateway.create_theme({'name': parser.name})
            if response.ok:
                theme = response.json()
                if theme and theme.get('id'):
                    self.config.theme_id = theme['id']
                    self.config.save()
                    logging.info(
                        f'[{self.config.env}] Theme [{theme["id"]}] "{theme["name"]}" has been created successfully.')
            else:
                logging.error(
                    f'[{self.config.env}] Theme "{parser.name}" has been created failed.')
        else:
            raise TypeError(f'[{self.config.env}] argument -n/--name is required.')

    @parser_config(theme_id_required=False)
    def list(self, parser):
        response = self.gateway.get_themes()
        themes = response.json()
        if themes and themes.get('results'):
            logging.info(f'[{self.config.env}] Available themes:')
            for theme in themes['results']:
                logging.info(f'[{self.config.env}] \t[{theme["id"]}] \t{theme["name"]}')
        else:
            logging.warning(f'[{self.config.env}] Missing Themes in {self.config.store}')

    @parser_config()
    def pull(self, parser):
        self._pull_themplates(parser.filenames)

    @parser_config(write_file=True)
    def checkout(self, parser):
        self._pull_themplates([])

    @parser_config()
    def push(self, parser):
        self.config.parser_config(parser)
        template_names = []
        if parser.filenames:
            template_names += parser.filenames
        else:
            for (dirpath, dirnames, filenames) in os.walk(os.getcwd()):
                template_names += [os.path.relpath(os.path.join(dirpath, file)) for file in filenames]
        self._push_themplates(template_names)

    @parser_config()
    def watch(self, parser):
        self.config.parser_config(parser)
        current_pathfile = os.path.join(os.getcwd())
        logging.info(f'[{self.config.env}] Current store {self.config.store}')
        logging.info(f'[{self.config.env}] Current theme id {self.config.theme_id}')
        logging.info(f'[{self.config.env}] Preview theme URL {self.config.store}?preview_theme={self.config.theme_id}')
        logging.info(f'[{self.config.env}] Watching for file changes in {current_pathfile}')
        logging.info(f'[{self.config.env}] Press Ctrl + C to stop')

        async def main():
            async for changes in awatch('.'):
                self._handle_files_change(changes)

        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
