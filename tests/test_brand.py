"""The brand images shipped with the integration."""

from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration
from PIL import Image

from custom_components.luxpower_local.const import DOMAIN

ICONS = {"icon.png": 256, "icon@2x.png": 512}
LOGOS = {
    "logo.png": 128,
    "logo@2x.png": 256,
    "dark_logo.png": 128,
    "dark_logo@2x.png": 256,
}


async def test_brand_images(hass: HomeAssistant) -> None:
    """Home Assistant picks up the local brand folder; icons are square PNGs."""
    integration = await async_get_integration(hass, DOMAIN)
    assert integration.has_branding

    brand_dir = Path(integration.file_path) / "brand"
    assert sorted(p.name for p in brand_dir.iterdir()) == sorted({**ICONS, **LOGOS})
    for name, size in ICONS.items():
        with Image.open(brand_dir / name) as image:
            assert (image.format, image.mode, image.size) == ("PNG", "RGBA", (size, size))
    for name, height in LOGOS.items():
        with Image.open(brand_dir / name) as image:
            assert (image.format, image.mode, image.height) == ("PNG", "RGBA", height)
            assert image.width > height
