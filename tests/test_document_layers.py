from models import Document, TextLayer, add_image_layer, add_text_layer, delete_layer, move_layer
from renderer import render_document_png


def test_add_multiple_assets_updates_document_layer_count(tmp_path):
    first = tmp_path / "a.svg"
    second = tmp_path / "b.svg"
    first.write_text('<svg viewBox="0 0 10 10" xmlns="http://www.w3.org/2000/svg"><path d="M0 0L10 10"/></svg>', encoding="utf-8")
    second.write_text('<svg viewBox="0 0 10 10" xmlns="http://www.w3.org/2000/svg"><path d="M0 10L10 0"/></svg>', encoding="utf-8")
    document = Document()

    add_image_layer(document, first)
    add_image_layer(document, second)

    assert len(document.layers) == 2
    assert document.selected_layer_id == document.layers[-1].id


def test_add_asset_does_not_replace_existing_asset(tmp_path):
    first = tmp_path / "first.svg"
    second = tmp_path / "second.svg"
    first.write_text("<svg />", encoding="utf-8")
    second.write_text("<svg />", encoding="utf-8")
    document = Document()

    first_layer = add_image_layer(document, first, name="First")
    second_layer = add_image_layer(document, second, name="Second")

    assert document.layers[0] is first_layer
    assert document.layers[1] is second_layer
    assert document.layers[0].path == first


def test_layer_order_change_controls_rendering_order(tmp_path):
    document = Document()
    bottom = add_image_layer(document, tmp_path / "bottom.svg", name="Bottom")
    top = add_text_layer(document, "Top", name="Top")

    assert document.sorted_layers() == [bottom, top]
    move_layer(document, bottom.id, "top")

    assert document.sorted_layers() == [top, bottom]


def test_text_layer_can_change_text_and_render_again(tmp_path):
    document = Document(canvas_width=200, canvas_height=100)
    layer = add_text_layer(document, "Before", x=10, y=10, width=120, height=50, font_size=24)
    layer.text = "After"

    output = render_document_png(document, tmp_path / "text.png")

    assert output.exists()
    assert isinstance(document.layers[0], TextLayer)
    assert document.layers[0].text == "After"


def test_delete_selected_layer_updates_selection(tmp_path):
    document = Document()
    first = add_image_layer(document, tmp_path / "first.svg")
    second = add_text_layer(document, "Second")

    removed = delete_layer(document, second.id)

    assert removed is second
    assert document.selected_layer_id == first.id


def test_image_layer_stores_independent_material_geometry(tmp_path):
    document = Document()
    layer = add_image_layer(
        document,
        tmp_path / "rose.svg",
        name="Rose layer",
        x=10,
        y=20,
        width=300,
        height=400,
        material_id="rose-1",
        material_name="Rose June",
    )

    layer.x = 99
    layer.width = 199

    assert layer.material_id == "rose-1"
    assert layer.material_name == "Rose June"
    assert layer.x == 99
    assert layer.y == 20
    assert layer.width == 199
    assert layer.height == 400
    assert layer.lock_aspect_ratio is True
