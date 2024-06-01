from app import App

class HelloWorld(App):
  def __init__(self):
    pass

  def update(self):
    pass:

  def draw(self):
    ctx.move_to(0, 0).text("Hello, world!"]

__app_export__ = HelloWorld
