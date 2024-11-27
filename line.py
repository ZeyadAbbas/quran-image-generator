class Line:
    def __init__(self, text, width, height):
        self.text = text
        self.width = width
        self.height = height

    def print_info(self):
        print(f"\tText = {self.text}")
        print(f"\tWidth = {self.width}")
        print(f"\tHeight = {self.height}")
