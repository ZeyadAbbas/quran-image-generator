import random

from models import GenerationRequest
from quran_image_generator import build_generator
from settings import load_settings

VERSE_BOUNDS_FILE = "assets/verse_bounds.txt"
with open(VERSE_BOUNDS_FILE) as verse_bounds_file:
    maxes = verse_bounds_file.readlines()


def get_inputs():
    while True:
        try:
            chapter = int(input("\nInput chapter: "))
            if chapter > 114 or chapter < 1:
                raise ValueError("Input out of bounds")
            break
        except ValueError:
            print("Invalid input. Please input an integer value between 1 and 114.")

    chapter_max_verses = int(maxes[chapter - 1])

    while True:
        try:
            starting_verse = int(input("Input starting verse: "))
            if starting_verse > chapter_max_verses or starting_verse < 1:
                raise ValueError("Input out of bounds")
            break
        except ValueError:
            print(
                "Invalid input. Please input an integer value between "
                f"1 and {chapter_max_verses}."
            )

    while True:
        try:
            ending_verse = int(input("Input ending verse: "))
            if ending_verse > chapter_max_verses or ending_verse < starting_verse:
                raise ValueError("Input out of bounds")
            break
        except ValueError:
            print(
                "Invalid input. Please input an integer value between "
                f"{starting_verse} and {chapter_max_verses}."
            )

    return chapter, starting_verse, ending_verse


def get_randoms():
    chapter = random.randint(1, 114)
    chapter_max_verses = int(maxes[chapter - 1])
    starting_verse = random.randint(1, chapter_max_verses)
    ending_verse = random.randint(starting_verse, starting_verse + random.randint(1, 4))
    ending_verse = min(ending_verse, chapter_max_verses)

    return chapter, starting_verse, ending_verse


def run():
    while True:
        settings = load_settings()
        if settings.generate_random_verses:
            chapter, starting_verse, ending_verse = get_randoms()
        else:
            chapter, starting_verse, ending_verse = get_inputs()

        generator = build_generator(settings)
        result = generator.generate(
            GenerationRequest(chapter, starting_verse, ending_verse),
            publish=settings.upload is True,
            open_output=True,
        )

        if settings.upload == "ask" and result.path is not None:
            while True:
                reload = input("Post? [y/n]: ").lower()
                if reload == "n":
                    break
                if reload == "y":
                    generator.publish(result.path)
                    break

        while True:
            reload = input("Generate another? [y/n]: ").lower()
            if reload == "n":
                raise SystemExit
            if reload == "y":
                break


if __name__ == "__main__":
    run()
