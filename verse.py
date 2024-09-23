import read_config as config
from translation import Translation
from line import Line
from wand.image import Image
from wand.drawing import Drawing


class Verse:
    def __init__(self, data):
        self.data = data
        self.translations_data = data["verse"]["translations"] if "translations" in data["verse"] else None
        self.words = self.get_verse_words_from_api_data()

        self.font = config.quran_font()
        self.font_size = config.quran_font_size()
        self.fill_color = config.quran_color()
        self.letter_spacing = config.quran_letter_spacing()
        self.max_width = config.quran_max_width()
        self.word_spacing = config.quran_word_spacing()
        self.max_width = config.quran_max_width()
        self.word_spacing = config.quran_word_spacing()

        self.lines = self.get_lines()
        self.translations = self.set_translations() if self.translations_data else None
        self.number = data["verse"]["verse_number"]
        self.height = self.get_height()

    def get_verse_words_from_api_data(self):
        words = self.data["verse"]['words']
        words.pop(len(words) - 1)
        for i, word in enumerate(words):
            words[i] = word['text']

        return words

    def get_translation(self):
        pass

    def set_translations(self):
        translations = [None] * len(self.translations_data)
        for data in self.translations_data:
            translation = Translation(data)
            index = list((config.translation_languages()).keys()).index(translation.code)
            translations[index] = translation

        return translations

    def get_lines(self):
        if config.quran_x_position() != 'center':
            starting_x_pos = config.quran_x_position()
        else:
            starting_x_pos = 0

        lines = []
        current_line = ''
        with Image(width=1, height=1) as temp_img:
            with Drawing() as draw:
                self.set_draw_settings(draw)
                for i, word in enumerate(self.words):
                    test_line = current_line + self.word_spacing + word if current_line else word
                    metrics = draw.get_font_metrics(temp_img, test_line)
                    verse_number_width, verse_number_height = config.verse_number_resolution()
                    verse_number_offsets = (verse_number_width + config.verse_number_x_offset())
                    if metrics.text_width < self.max_width:
                        current_line = test_line
                    elif i >= len(self.words) - 1 and metrics.text_width < self.max_width - starting_x_pos - verse_number_offsets:
                        metrics = draw.get_font_metrics(temp_img, current_line)
                        lines.append(Line(current_line, metrics.text_width, metrics.text_height))
                        current_line = word
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
        line_spacing = config.quran_line_spacing()
        for line in self.lines:
            total_height += line.height + line_spacing
        total_height -= line_spacing

        return total_height

    def set_draw_settings(self, draw):
        draw.font = self.font
        draw.font_size = self.font_size
        draw.fill_color = self.fill_color
        draw.text_kerning = self.letter_spacing
        draw.max_width = self.max_width
        draw.word_spacing = self.word_spacing

    def print_info(self):
        print(f"\nWords = {self.words}")
        for line in self.lines:
            print('\nLine = {')
            line.print_info()
            print('}')
        if self.translations:
            for translation in self.translations:
                print('\nTranslation = {')
                translation.print_info()
                print('}')
        print(f"\nNumber = {self.number}")
        print(f"\nHeight = {self.height}\n")
