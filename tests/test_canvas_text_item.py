from models import TextLayer
from canvas_text_item import CanvasTextItem


def test_canvas_text_item_resize_updates_text_box_and_rerenders():
    layer = TextLayer(text="Rose", width=120, height=48, text_box_width=120, text_box_height=48)
    item = CanvasTextItem(layer)

    item.resize_by(30, 12)
    result = item.render()

    assert layer.width == 150
    assert layer.height == 60
    assert layer.text_box_width == 150
    assert layer.text_box_height == 60
    assert result.image.size == (150, 60)


def test_canvas_text_item_move_keeps_render_data_layer_based():
    layer = TextLayer(text="Rose", x=10, y=20, width=120, height=48, text_box_width=120, text_box_height=48)
    item = CanvasTextItem(layer)

    item.move_by(5, -3)
    result = item.render()

    assert layer.x == 15
    assert layer.y == 17
    assert result.render_text == "Rose"

