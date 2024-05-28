import app
import asyncio
import random

from app_components import YesNoDialog, clear_background
from events.input import Buttons, BUTTON_TYPES


class SnakeApp(app.App):
    def __init__(self):
        # Need to call to access overlays
        super().__init__()
        self.button_states = Buttons(self)
        self.snake = [(16, 16)]
        self.food = []
        self.direction = ""
        self.step = 0
        self.score = 0
        self.game = ""
        self.dialog = None

    def _reset(self):
        self.snake = [(16,16)]
        self.food = []
        self.direction = ""
        self.score = 0
        self.dialog = None

    def _exit(self):
        self._reset()
        self.button_states.clear()
        self.minimise()


    def update(self, delta):
        if self.button_states.get(BUTTON_TYPES["RIGHT"]):
            self.direction = "RIGHT"
            self.game = "ON"
        elif self.button_states.get(BUTTON_TYPES["LEFT"]):
            self.direction = "LEFT"
            self.game = "ON"
        elif self.button_states.get(BUTTON_TYPES["UP"]):
            self.direction = "UP"
            self.game = "ON"
        elif self.button_states.get(BUTTON_TYPES["DOWN"]):
            self.direction = "DOWN"
            self.game = "ON"
        elif self.button_states.get(BUTTON_TYPES["CANCEL"]):
            self.button_states.clear()
            self.game = ""
            self.minimise()

        # Only move snake every half second
        self.step = self.step + delta
        if self.game == "ON":
            if self.step > 500:
                self.step = 0
                self._move_snake()
        elif self.game == "OVER":
            self.dialog = YesNoDialog(
                message="Game Over.\nPlay Again?",
                on_yes=self._reset,
                on_no=self._exit,
                app=self,
            )
            # Reset the game variable to ensure this dialog is only created once
            self.game = ""

    def _move_snake(self):
        first_x, first_y = self.snake[0]
        if self.direction == "RIGHT":
            self.snake = [(first_x + 1, first_y)] + self.snake
            self.snake = self.snake[:-1]
        if self.direction == "LEFT":
            self.snake = [(first_x - 1, first_y)] + self.snake
            self.snake = self.snake[:-1]
        if self.direction == "UP":
            self.snake = [(first_x, first_y - 1)] + self.snake
            self.snake = self.snake[:-1]
        if self.direction == "DOWN":
            self.snake = [(first_x, first_y + 1)] + self.snake
            self.snake = self.snake[:-1]

        # if there is food there, eat food
        if self.snake[0] in self.food:
            self.food.remove(self.snake[0])
            self.snake = self.snake + [self.snake[0]]
            self.score = self.score + 1

        # check if outside game borders
        x, y = self.snake[0]
        if x < 0 or x >= 32:
            self.game = "OVER"
        if y < 0 or y >= 32:
            self.game = "OVER"

    def _generate_food(self):
        coordinates = (random.randrange(32), random.randrange(32))
        if not coordinates in self.food:
            self.food = self.food + [coordinates]

    async def background_task(self):
        while True:
            await asyncio.sleep(5)
            if self.game == "ON":
                self._generate_food()

    def draw(self, ctx):
        clear_background(ctx)
        ctx.save()

        # draw score
        ctx.font_size = 12
        width = ctx.text_width("Score: {}".format(self.score))
        ctx.rgb(1,0,0).move_to(0 - width/2,100).text("Score: {}".format(self.score))

        ctx.translate(-80,-80)
        # draw game board
        ctx.rgb(0, 0, 0).rectangle(0, 0, 160, 160).fill()

        # draw food
        for x, y in self.food:
            ctx.rgb(0, 1, 0).rectangle(x*5, y*5, 5, 5).fill()

        # draw snake
        for x, y in self.snake:
            ctx.rgb(0, 0, 1).rectangle(x*5, y*5, 5, 5).fill()

        ctx.restore()

        if self.dialog:
            self.dialog.draw(ctx)
