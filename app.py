from app import App
from app_components import clear_background

class HelloWorld(App):
  def __init__(self):
    pass

  def update(self):
    pass

  def draw(self, ctx):
    clear_background(ctx)
    ctx.text_align = ctx.CENTER
    ctx.text_baseline = ctx.MIDDLE
    ctx.move_to(0, 0).gray(1).text("Hello, world!"]

__app_export__ = HelloWorld
