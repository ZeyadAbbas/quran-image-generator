import read_config as config
from verse import Verse
import requests
import os
from wand.image import Image
from wand.drawing import Drawing
from instagrapi import Client

VERSE_NUMBERS_FOLDER = 'assets/verse_numbers'


class QuranImageGenerator:
    def __init__(self, chapter, starting_verse, ending_verse):
        self.chapter = chapter
        self.starting_verse = starting_verse
        self.ending_verse = ending_verse
        self.verses = []
        self.translation_codes = ''
        language_codes = config.translation_languages()
        for key in language_codes:
            self.translation_codes += f", {key}" if self.translation_codes else key
        self.image_path = None

    def format_verse_keys(self):
        keys = []
        current_verse_number = self.starting_verse
        while current_verse_number <= self.ending_verse:
            keys.append(f"{self.chapter}:{current_verse_number}")
            current_verse_number += 1

        return keys

    def api_call(self, endpoint):
        headers = {'Accept': 'application/json'}
        params = {'translations': self.translation_codes, 'words': 1, 'word_fields': 'text_uthmani', }

        uri = f"https://api.quran.com/api/v4/{endpoint}"
        response = requests.get(uri, headers=headers, data={}, params=params)
        return response.json()

    def fetch_verses(self):
        verse_keys = self.format_verse_keys()
        for key in verse_keys:
            verse_data = self.api_call(f"verses/by_key/{key}")
            verse = Verse(verse_data)
            self.verses.append(verse)

    def create_image(self):
        if len(self.verses) != 0:
            width, height = config.resolution()
            with Image(width=width, height=height, pseudo=config.background_color()) as image:
                if config.background_image():
                    with Image(filename=config.background_image()) as back:
                        image.composite(back, int(0), int(0))

                with Drawing() as draw:
                    total_verses_height = 0
                    total_translations_height = 0
                    for verse in self.verses:
                        verse.set_draw_settings(draw)
                        total_verses_height += verse.height
                        total_verses_height += config.space_between_verses()
                        if self.translation_codes:
                            for translation in verse.translations:
                                translation.set_draw_settings(draw)
                                total_translations_height += translation.height
                                total_translations_height += config.quran_translation_spacing()

                    total_verses_height -= config.space_between_verses()
                    total_text_height = total_verses_height + total_translations_height
                    verse_y_pos = ((height - total_text_height) // 2) + config.total_y_offset()

                    for verse in self.verses:
                        verse.set_draw_settings(draw)
                        line_y_pos = verse_y_pos
                        for line in verse.lines:
                            line_y_pos += line.height
                            if config.quran_x_position() == 'center':
                                x_pos = (width / 2) - (line.width // 2)
                            else:
                                x_pos = abs(width - line.width - config.quran_x_position())

                            draw.text(int(x_pos), int(line_y_pos), line.text)
                            added_height = config.quran_line_spacing()
                            line_y_pos += added_height

                        line_y_pos -= config.quran_line_spacing()
                        if config.verse_numbers_visible():
                            png_path = f"{VERSE_NUMBERS_FOLDER}/{verse.number}.png"
                            try:
                                with Image(filename=png_path) as verse_number_image:
                                    verse_number_width, verse_number_height = config.verse_number_resolution()
                                    x_offset = config.verse_number_x_offset()
                                    y_offset = config.verse_number_y_offset()
                                    verse_number_image.resize(verse_number_width, verse_number_height)
                                    image.composite(verse_number_image, int(x_pos - x_offset - width),
                                                    int(line_y_pos - y_offset))
                            except Exception as e:
                                print(f"Error loading {png_path}: {e}")

                        if self.translation_codes:
                            line_y_pos += config.quran_translation_spacing()
                            for translation in verse.translations:
                                translation.set_draw_settings(draw)
                                for line in translation.lines:
                                    line_y_pos += line.height
                                    if config.translation_x_position() == 'center':
                                        x_pos = (width / 2) - (line.width // 2)
                                    else:
                                        x_pos = config.translation_x_position()

                                    draw.text(int(x_pos), int(line_y_pos), line.text)
                                    added_height = config.translation_line_spacing()
                                    line_y_pos += added_height
                                line_y_pos -= config.translation_line_spacing()
                                line_y_pos += config.translation_language_spacing()

                            line_y_pos -= config.translation_language_spacing()
                        verse_y_pos = line_y_pos + config.space_between_verses()

                    draw(image)

                chapter_info = self.api_call(f"chapters/{self.chapter}")
                file_name = f"{chapter_info['chapter']['name_simple']} {self.verses[0].number}"
                file_name += f" - {self.verses[-1].number}.png" if len(self.verses) > 1 else ".png"

                file_path = os.path.join(config.output_path(), file_name)
                self.image_path = file_path
                image.save(filename=file_path)

            print(f"\nImage Created.\n")

    def open_image(self):
        os.system(f'start "" "{self.image_path}"')

    def post(self, username, password):
        post_to = config.post_method()
        if 'insta' in post_to:
            print(f'\nAccessing account "{username}"')
            client = Client()
            client.login(username, password)
            if post_to == 'insta_story':
                print(f'\nPosting as instagram story on account "{username}"')
                client.photo_upload_to_story(self.image_path)
            elif post_to == 'insta_post':
                print(f'\nPosting as instagram post on account "{username}"')
                client.photo_upload(self.image_path, "quran")
        else:
            print(f'\nUnable to use post method, check the post method in the config file.')
