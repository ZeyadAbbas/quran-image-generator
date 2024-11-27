import yaml
import os
from colorama import Fore, init
from wand.image import Image

init(autoreset=True)


config = {}

def load_config():
    global config
    with open('config.yaml', 'r', encoding='utf-8') as file:
        config = yaml.safe_load(file)
    file.close()

load_config()

with open('assets/translation_codes/translation_codes.yaml', 'r', encoding='utf-8') as file:
    languages = yaml.safe_load(file)


def print_warning(message):
    print(f"{Fore.YELLOW}[WARNING] {message}")


def print_error(message):
    print(f"{Fore.RED}[ERROR] {message}")


DEFAULTS = {
    'output path': 'outputs',
    'resolution': '1080 x 1080',
    'background color': '000000',
    'quran color': 'FFFFFF',
    'quran font': 'Arial',
    'quran font size': 34,
    'quran x position': 30,
    'quran maximum width': 700,
    'quran line spacing': 30,
    'quran word spacing': 6,
    'quran letter spacing': -0.1,
    'quran and translation spacing': 30,
    'translation languages': '',
    'translation color': '#FFFFFF',
    'translation font size': 16,
    'translation x position': 40,
    'translation maximum width': 650,
    'translation language spacing': 10,
    'translation line spacing': 10,
    'translation word spacing': 1,
    'translation letter spacing': 0.0,
    'show verse numbers': False,
    'verse number resolution': '55 x 55',
    'verse number x offset': 10,
    'verse number y offset': -20,
    'space between verses': 70,
    'generate random verses': False,
    'total y offset': -10,
    'upload': False
}


# Output Path
def output_path():
    try:
        output_directory = config['output path']
        if output_directory and not os.path.isdir(output_directory):
            raise FileNotFoundError(f'"{output_directory}" not found.')
        raise ValueError(f'No output directory specified.')
    except Exception as e:
        print_warning(f"{e} Resorted to using the default output directory ({DEFAULTS['output path']})")
        if not os.path.isdir('outputs'):
            os.makedirs("outputs")
        output_directory = DEFAULTS['output path']

    return output_directory


# Background Image
def background_image():
    try:
        background_image = config['background image']
        if not os.path.exists(background_image):
            raise FileNotFoundError(f"Background image file not found.")
    except FileNotFoundError as e:
        print_warning(f'{e} Resorted to not using no background image')
        background_image = ''

    return background_image


# Resolution
def resolution():
    try:
        res = config['resolution'].lower()
        if res == 'bg':
            with Image(filename=background_image()) as img:
                width = img.width
                height = img.height
        elif len(res.split('x')) == 2:
            res = res.split('x')
            width = int(res[0])
            height = int(res[1])
        else:
            raise Exception(f"Resolution does not contain exactly one 'x' with numbers on both sides.")

    except Exception as e:
        if isinstance(e, ValueError):
            e = f'Input (width or height) is not a number.'
        print_warning(f"{e} Resorted to using the default resolution ({DEFAULTS['resolution']})")
        res = DEFAULTS['resolution'].split('x')
        width = int(res[0])
        height = int(res[1])

    return width, height


# Background Color
def background_color():
    try:
        bg_hex = config['background color']
        if '#' in bg_hex:
            if bg_hex[0] == '#':
                bg_hex = bg_hex[1:]
            else:
                raise ValueError('HEX code hashtag (#) not placed in the correct positioning.')

        if '#' not in bg_hex:
            if len(bg_hex) == 6:
                background_color = f"xc:#{bg_hex}"
            else:
                raise ValueError("HEX code is the incorrect length.")
        else:
            raise ValueError('HEX code hashtag (#) not placed in the correct positioning.')
    except ValueError as e:
        print_warning(f"{e} Resorted to using the default background color (#{DEFAULTS['background color']})")
        background_color = f"xc:#{DEFAULTS['background color']}"

    return background_color


# Quran Font
def quran_font():
    try:
        quran_font = config['quran font']
        if not os.path.exists(quran_font):
            raise FileNotFoundError(f"'{quran_font}' file not found.")
    except FileNotFoundError as e:
        print_warning(f"{e} Resorted to using the default Quran font ({DEFAULTS['quran font']})")
        quran_font = DEFAULTS['quran font']

    return quran_font


# Quran Color
def quran_color():
    config_input = config['quran color']
    try:
        quran_hex = config_input
        if '#' in quran_hex:
            if quran_hex[0] == '#':
                quran_hex = quran_hex[1:]
            else:
                raise ValueError('HEX code hashtag (#) not placed in the correct positioning.')

        if '#' not in quran_hex:
            if len(quran_hex) == 6:
                quran_color = f"#{quran_hex}"
            else:
                raise ValueError("HEX code is the incorrect length.")
        else:
            raise ValueError('HEX code hashtag (#) not placed in the correct positioning.')
    except ValueError as e:
        print_warning(f"{e} Resorted to using the default Quran color ({DEFAULTS['quran color']})")
        quran_color = f"#{DEFAULTS['quran color']}"

    return quran_color


# Quran Font Size
def quran_font_size():
    config_input = config['quran font size']
    try:
        quran_font_size = int(config_input)
    except Exception:
        e = f"'{config_input}' is not a number."
        print_warning(f"{e} Resorted to using the default Quran font size ({DEFAULTS['quran font size']})")
        quran_font_size = DEFAULTS['quran font size']

    return quran_font_size


# Quran X Position
def quran_x_position():
    config_input = config['quran x position']
    try:
        quran_x_position = int(config_input)
    except Exception:
        if config_input.lower() == 'center':
            quran_x_position = 'center'
        else:
            e = f"'{config_input}' is not a number."
            print_warning(f"{e} Resorted to using the default Quran x position ({DEFAULTS['quran x position']})")
            quran_x_position = DEFAULTS['quran x position']

    return quran_x_position



# Translation Font Size
def translation_font_size():
    try:
        translation_font_size = int(config['translation font size'])
    except Exception as e:
        default = DEFAULTS['translation font size']
        if isinstance(e, ValueError):
            e = f'Input is not a number.'
        print_warning(f'{e} Resorted to using the default translation font size ({default})')
        translation_font_size = default

    return translation_font_size


# Translation Languages
def translation_languages():
    language_codes = {}
    exceptions = []
    try:
        input_translation_codes = config['translation languages'].split(',')
        for i, code_combination in enumerate(input_translation_codes):
            try:
                language_data = code_combination.split(':')
                language_code = language_data[0]
                if len(language_data) == 3:
                    language_font = language_data[1]
                    language_font_size = language_data[2]
                elif len(language_data) == 2:
                    try:
                        language_font_size = int(language_data[1])
                        language_font = None
                    except:
                        language_font = language_data[1]
                        language_font_size = None
                else:
                    language_font = None
                    language_font_size = None

            except Exception as e:
                language_code = code_combination
                language_font = None
                language_font_size = None
                exceptions.append(ValueError(f'No font and font size selected for "{language_code}" language code.'))

            try:
                language_code = language_code.replace(" ", "") if ' ' in language_code else language_code
                if language_code in languages:
                    if len(language_codes) < 3:
                        language_iso = language_code
                        language_code = languages[language_code]
                        language_codes[language_code] = {}
                    else:
                        raise IndexError(f'Too many translation languages were inputted, '
                                         f"'{language_code}' and what's beyond will not be shown.")
                else:
                    raise ValueError(f'"{language_code}" is not a valid language code.')
            except Exception as e:
                exceptions.append(e)
                if isinstance(e, ValueError):
                    language_code = None

            try:
                if language_code:
                    if language_font:
                        if language_font.endswith('.ttf') or language_font.endswith('.otf'):
                            language_font_path = f"assets/fonts/{language_font}"
                            if os.path.exists(language_font_path):
                                language_codes[language_code]['font'] = language_font_path
                            else:
                                raise FileNotFoundError(f'"{language_font_path}" file not found.')
                        elif language_font == 'Arial':
                            language_codes[language_code]['font'] = 'Arial'
                        else:
                            raise ValueError(f'"{language_font}" is not a valid font file (.ttf / .otf).')
                    else:
                        raise ValueError(f'No font selected for "{language_code}" language code. '
                                         f'Resorted to using the default language font (assets/fonts/multilingual_fonts)')
            except Exception as e:
                exceptions.append(e)
                if language_code:
                    if os.path.exists(f'assets/fonts/multilingual_fonts/{language_iso}.ttf'):
                        language_codes[language_code]['font'] = f'assets/fonts/multilingual_fonts/{language_iso}.ttf'
                    elif os.path.exists(f'assets/fonts/multilingual_fonts/{language_iso}.otf'):
                        language_codes[language_code]['font'] = f'assets/fonts/multilingual_fonts/{language_iso}.otf'
                    else:
                        language_codes[language_code]['font'] = 'Arial'

            if language_font_size:
                language_codes[language_code]['font_size'] = int(language_font_size)
            else:
                language_codes[language_code]['font_size'] = int(translation_font_size())


    except Exception as e:
        if isinstance(e, IndexError):
            print_warning(f'No language codes provided. Resorted to using no translation.')
    finally:
        pass

    return language_codes


# Translation Color
def translation_color():
    try:
        t_hex = config['translation color']
        if '#' in t_hex:
            if t_hex.index('#') == 0:
                t_hex = t_hex[1:len(t_hex)]
            else:
                raise ValueError("Invalid HEX provided.")

        if len(t_hex) == 6:
            translation_color = f"#{t_hex}"
        else:
            raise ValueError("Invalid HEX provided.")
    except ValueError as e:
        translation_color = DEFAULTS['translation color']

    return translation_color


# Quran Verse Maximum Width
def quran_max_width():
    try:
        quran_max_width = int(config['quran maximum width'])
    except ValueError as e:
        quran_max_width = DEFAULTS['quran maximum width']

    return quran_max_width


# Quran Line Spacing
def quran_line_spacing():
    try:
        quran_line_spacing = int(config['quran line spacing'])
    except ValueError as e:
        quran_line_spacing = DEFAULTS['quran line spacing']

    return quran_line_spacing


# Quran Word Spacing
def quran_word_spacing():
    try:
        i_quran_word_spacing = int(config['quran word spacing'])

        quran_word_spacing = ' ' * i_quran_word_spacing
    except ValueError as e:
        quran_word_spacing = ' ' * DEFAULTS['quran word spacing']

    return quran_word_spacing


# Quran Letter Spacing
def quran_letter_spacing():
    try:
        quran_letter_spacing = float(config['quran letter spacing'])
    except ValueError as e:
        quran_letter_spacing = DEFAULTS['quran letter spacing']

    return quran_letter_spacing




# Translation Maximum Width
def translation_max_width():
    try:
        translation_max_width = int(config['translation maximum width'])
    except ValueError as e:
        translation_max_width = DEFAULTS['translation maximum width']

    return translation_max_width


# Translation Line Spacing
def translation_line_spacing():
    try:
        translation_line_spacing = int(config['translation line spacing'])
    except ValueError as e:
        translation_line_spacing = DEFAULTS['translation line spacing']

    return translation_line_spacing


# Translation Word Spacing
def translation_word_spacing():
    try:
        i_translation_word_spacing = int(config['translation word spacing'])

        translation_word_spacing = ' ' * i_translation_word_spacing
    except ValueError as e:
        translation_word_spacing = ' ' * DEFAULTS['translation word spacing']

    return translation_word_spacing


# Translation Letter Spacing
def translation_letter_spacing():
    try:
        translation_letter_spacing = float(config['translation letter spacing'])
    except ValueError as e:
        translation_letter_spacing = DEFAULTS['translation letter spacing']

    return translation_letter_spacing


# Translation Language Spacing
def translation_language_spacing():
    try:
        translation_language_spacing = int(config['translation language spacing'])
    except ValueError as e:
        translation_language_spacing = DEFAULTS['translation language spacing']

    return translation_language_spacing


# Translation X Position
def translation_x_position():
    try:
        translation_x_position = int(config['translation x position'])
    except ValueError as e:
        if config['translation x position'] == 'center':
            translation_x_position = 'center'
        else:
            translation_x_position = DEFAULTS['translation x position']

    return translation_x_position


# Quran And Translation Spacing
def quran_translation_spacing():
    try:
        quran_translation_spacing = int(config['quran and translation spacing'])
    except ValueError as e:
        quran_translation_spacing = DEFAULTS['quran and translation spacing']

    return quran_translation_spacing


# Space Between Verses
def space_between_verses():
    try:
        space_between_verses = int(config['space between verses'])
    except ValueError as e:
        space_between_verses = DEFAULTS['space between verses']

    return space_between_verses


# Show Verse Numbers
def verse_numbers_visible():
    try:
        verse_numbers_visible = config['show verse numbers'].lower()
        if verse_numbers_visible == 'true':
            verse_numbers_visible = True
        elif verse_numbers_visible == 'false':
            verse_numbers_visible = False
        else:
            raise ValueError('Invalid input')
    except ValueError as e:
        verse_numbers_visible = DEFAULTS['show verse numbers']

    return verse_numbers_visible


# Verse Number Resolution
def verse_number_resolution():
    try:
        verse_number_resolution = config['verse number resolution'].lower().split('x')
        if len(verse_number_resolution) == 2:
            verse_number_width = int(verse_number_resolution[0])
            verse_number_height = int(verse_number_resolution[1])
        else:
            raise Exception(f"Resolution does not contain exactly one 'x' with numbers on both sides.")
    except Exception as e:
        if isinstance(e, ValueError):
            e = f'Input (width or height) is not a number.'
        print_warning(f'{e} Resorted to using the default resolution (55 x 55)')
        verse_number_width = 55
        verse_number_height = 55

    return verse_number_width, verse_number_height


# Verse Number X Offset
def verse_number_x_offset():
    try:
        verse_number_x_offset = int(config['verse number x offset'])
        if verse_number_x_offset < -20 or verse_number_x_offset > 500:
            raise ValueError("Input out of bound")
    except ValueError as e:
        verse_number_x_offset = DEFAULTS['verse number x offset']

    return verse_number_x_offset


# Verse Number Y Offset
def verse_number_y_offset():
    try:
        verse_number_y_offset = int(config['verse number y offset'])
    except ValueError as e:
        verse_number_y_offset = DEFAULTS['verse number y offset']

    return verse_number_y_offset


# Generate Random Verses
def generate_random_verses():
    try:
        generate_random_verses = config['generate random verses'].lower()
        if generate_random_verses == 'true':
            generate_random_verses = True
        elif generate_random_verses == 'false':
            generate_random_verses = False
        else:
            raise ValueError('Invalid input')
    except ValueError as e:
        generate_random_verses = DEFAULTS['generate random verses']

    return generate_random_verses


# Total Y Offset
def total_y_offset():
    try:
        total_y_offset = int(config['total y offset'])
    except ValueError as e:
        total_y_offset = DEFAULTS['total y offset']

    return total_y_offset


# Upload Images Automatically
def upload():
    try:
        upload = config['upload'].lower()
        if upload == 'true':
            upload = True
        elif upload == 'false':
            upload = False
        elif upload == 'ask':
            upload = 'ask'
        else:
            raise ValueError('Invalid input')
    except ValueError as e:
        upload = DEFAULTS['upload']

    return upload


# Log in Username
def username():
    return config['username']


# Log in Password
def password():
    return config['password']


# Post Method
def post_method():
    return config['post method']