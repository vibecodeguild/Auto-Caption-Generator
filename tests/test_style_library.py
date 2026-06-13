from app.core.settings import CaptionStyle
from app.core.style_library import delete_user_style, is_built_in_style, load_style_library, save_user_style


def sample_style():
    return CaptionStyle(
        font_family="Montserrat",
        main_font_size=70,
        active_font_size=76,
        main_color="#FFFFFF",
        active_color="#FF00CE",
        outline_color="#05050A",
        outline_width=5,
        bold=True,
        active_bold=True,
        position="Bottom",
        margin_v=210,
    )


def test_load_style_library_includes_built_ins(tmp_path):
    library = load_style_library(tmp_path / "missing.json")

    assert "Magenta Pop" in library
    assert is_built_in_style("Magenta Pop")


def test_save_and_delete_user_style(tmp_path):
    path = tmp_path / "styles.json"

    save_user_style("My Style", sample_style(), path)
    library = load_style_library(path)

    assert library["My Style"].active_color == "#FF00CE"
    assert delete_user_style("My Style", path)
    assert "My Style" not in load_style_library(path)
