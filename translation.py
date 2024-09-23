import read_config as config
from line import Line
from wand.image import Image
from wand.drawing import Drawing
import re


class Translation:
    def __init__(self, translation_data):
        self.data = translation_data
        self.code = str(translation_data['resource_id'])
        self.words = self.get_and_format_translation_words_from_api_data()
        self.font = config.translation_languages()[self.code]['font']
        self.font_size = config.translation_languages()[self.code]['font_size']
        self.fill_color = config.translation_color()
        self.letter_spacing = config.translation_letter_spacing()
        self.max_width = config.translation_max_width()
        self.word_spacing = config.translation_word_spacing()
        self.lines = self.get_lines()
        self.height = self.get_height()

    def get_and_format_translation_words_from_api_data(self):
        pattern = re.compile(r'<[^<>]*>[^<>]*<[^<>]*>')
        translation_text = re.sub(pattern, '', self.data['text']).replace(u'\xa0', u' ')
        delimiters = ['˹', '˺']
        for delimeter in delimiters:
            translation_text = ''.join(translation_text.split(delimeter))
        translation_words = translation_text.split()
        return translation_words

    def get_lines(self):
        lines = []
        current_line = ''
        with Image(width=1, height=1) as temp_img:
            with Drawing() as draw:
                self.set_draw_settings(draw)
                for word in self.words:
                    test_line = current_line + self.word_spacing + word if current_line else word
                    metrics = draw.get_font_metrics(temp_img, test_line)
                    if metrics.text_width < self.max_width:
                        current_line = test_line
                    elif len(word) > 70:
                        current_line = word[:50]
                        metrics = draw.get_font_metrics(temp_img, current_line)
                        lines.append(Line(current_line, metrics.text_width, metrics.text_height))
                        current_line = word[50:]
                    else:
                        metrics = draw.get_font_metrics(temp_img, current_line)
                        lines.append(Line(current_line, metrics.text_width, metrics.text_height))
                        current_line = word

                if current_line:
                    metrics = draw.get_font_metrics(temp_img, current_line)
                    lines.append(Line(current_line, metrics.text_width, metrics.text_height))

            return lines

    def get_height(self):
        total_height = 0
        line_spacing = config.translation_line_spacing()
        language_spacing = config.translation_language_spacing()
        for line in self.lines:
            total_height += line.height + line_spacing
        total_height -= line_spacing
        total_height += language_spacing

        return total_height

    def set_draw_settings(self, draw):
        draw.font = self.font
        draw.font_size = self.font_size
        draw.fill_color = self.fill_color
        draw.text_kerning = self.letter_spacing
        draw.max_width = self.max_width
        draw.word_spacing = self.word_spacing

    def print_info(self):
        print(f"\tCode = {self.code}")
        print(f"\tWords = {self.words}")
        for line in self.lines:
            print('\nLine = {')
            line.print_info()
            print('}')
