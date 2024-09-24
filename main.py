from quran_image_generator import QuranImageGenerator
import read_config as config
import random

VERSE_BOUNDS_FILE = "assets/verse_bounds.txt"
file = open(VERSE_BOUNDS_FILE)
maxes = file.readlines()


def get_inputs():
    while True:
        try:
            chapter = int(input("\nInput chapter: "))
            if chapter > 114 or chapter < 1:
                raise ValueError("Input out of bounds")
            break
        except ValueError:
            print(f"Invalid input. Please input an integer value between 1 and 114.")

    chapter_max_verses = int(maxes[chapter - 1])

    while True:
        try:
            starting_verse = int(input("Input starting verse: "))
            if starting_verse > chapter_max_verses or starting_verse < 1:
                raise ValueError("Input out of bounds")
            break
        except ValueError:
            print(f"Invalid input. Please input an integer value between 1 and {chapter_max_verses}.")

    while True:
        try:
            ending_verse = int(input("Input ending verse: "))
            if ending_verse > chapter_max_verses or ending_verse < starting_verse:
                raise ValueError("Input out of bounds")
            break
        except ValueError:
            print(f"Invalid input. Please input an integer value between {starting_verse} and {chapter_max_verses}.")

    return chapter, starting_verse, ending_verse


def get_randoms():
    chapter = random.randint(1, 114)
    chapter_max_verses = int(maxes[chapter - 1])
    starting_verse = random.randint(1, chapter_max_verses)
    ending_verse = random.randint(starting_verse, starting_verse + random.randint(1, 4))
    if ending_verse > chapter_max_verses:
        ending_verse = chapter_max_verses

    return chapter, starting_verse, ending_verse


def run():
    while True:
        if config.generate_random_verses():
            chapter, starting_verse, ending_verse = get_randoms()
        else:
            chapter, starting_verse, ending_verse = get_inputs()
        config.load_config()
        gen = QuranImageGenerator(chapter, starting_verse, ending_verse)
        gen.fetch_verses()
        gen.create_image()
        gen.open_image()
        if config.upload():
            gen.post(config.username(), config.password())
        elif config.upload() == 'ask':
            while True:
                reload = input('Post? [y/n]: ').lower()
                if reload == 'n':
                    break
                elif reload == 'y':
                    gen.post(config.username(), config.password())
                    break
        while True:
            reload = input('Generate another? [y/n]: ').lower()
            if reload == 'n':
                exit()
            elif reload == 'y':
                break


if __name__ == '__main__':
    run()
