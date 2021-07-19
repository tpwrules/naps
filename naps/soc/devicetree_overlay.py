# utility functions for generating and loading devicetree overlays
from textwrap import dedent, indent

from nmigen import Fragment
from . import FatbitstreamContext

__all__ = ["devicetree_overlay"]

from . import File


def devicetree_overlay(platform, overlay_name, overlay_content, placeholder_substitutions_dict=None):
    if placeholder_substitutions_dict is None:
        placeholder_substitutions_dict = {}

    if not hasattr(platform, "devicetree_overlays"):
        platform.devicetree_overlays = dict()

        def overlay_hook(platform, top_fragment: Fragment, sames):
            assert hasattr(top_fragment, "memorymap")
            memorymap = top_fragment.memorymap

            for overlay_name, (overlay_content, placeholder_substitutions_dict) in reversed(platform.devicetree_overlays.items()):
                things_to_replace = {k: v if isinstance(v, str) else "0x{:x}".format(memorymap.find_recursive(v).address)
                                     for k, v in
                                     placeholder_substitutions_dict.items()}
                things_to_replace["overlay_name"] = overlay_name

                formatted_overlay_text = dedent(overlay_content)
                for name, replacement in things_to_replace.items():
                    formatted_overlay_text = formatted_overlay_text.replace("%{}%".format(name), replacement)

                overlay_text = dedent("""
                    /dts-v1/;
                    /plugin/;
    
                    / {
                        fragment@0 {
                            target = <&amba>;
    
                            __overlay__ {
                                %s
                            };
                        };
                    };
                """ % indent(formatted_overlay_text, "                                "))
                print(overlay_text)

                fc = FatbitstreamContext.get(platform)
                fc += File(f"{overlay_name}_overlay.dts", overlay_text)
                fc += "mkdir -p /sys/kernel/config/device-tree/overlays/{}\n".format(overlay_name)
                fc += f"dtc -O dtb -@ {overlay_name}_overlay.dts -o - > /sys/kernel/config/device-tree/overlays/{overlay_name}/dtbo\n\n"
        platform.prepare_hooks.append(overlay_hook)

    assert overlay_name not in platform.devicetree_overlays.keys()
    platform.devicetree_overlays[overlay_name] = (overlay_content, placeholder_substitutions_dict)

    return overlay_name
