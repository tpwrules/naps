import numpy as np
import sys
from PIL import Image

from util.plot_util import plt_hist, plt_image, plt_show

ty = np.int16


def wavelet1d(image, direction_x=False):
    img = image.T if direction_x else image

    def px(i):
        k = np.roll(img, -i, 0)
        return k[::2]

    lf_part = px(0) + px(1)
    hf_part = (px(0) - px(1)) + (-px(-2) - px(-1) + px(2) + px(3) + 4) // 8
    return np.hstack([lf_part.T, hf_part.T]) if direction_x else np.vstack([lf_part, hf_part])


def inverse_wavelet_1d(image, pad_width=0, direction_x=False):
    img = image.T if direction_x else image
    h, w = img.shape
    lf_part = np.pad(img[:h // 2], pad_width, "edge")
    hf_part = np.pad(img[h // 2:], pad_width, constant_values=0)

    x, y = lf_part.shape
    res = np.zeros((x * 2, y), dtype=ty)
    res[0::2] = (((np.roll(lf_part, +1, 0) - np.roll(lf_part, -1, 0) + 4) >> 3) + hf_part + lf_part) >> 1
    res[1::2] = (((-np.roll(lf_part, +1, 0) + np.roll(lf_part, -1, 0) + 4) >> 3) - hf_part + lf_part) >> 1

    pad_crop = res[2 * pad_width:-2 * pad_width, pad_width:-pad_width] if pad_width > 0 else res
    return pad_crop.T if direction_x else pad_crop


def wavelet2d(image):
    x_transformed = wavelet1d(image, direction_x=True)
    xy_transformed = wavelet1d(x_transformed)
    return xy_transformed


def inverse_wavelet_2d(image, pad_width=0):
    y_transformed = inverse_wavelet_1d(image, pad_width)
    return inverse_wavelet_1d(y_transformed, pad_width, direction_x=True)


def multi_stage_wavelet2d(image, stages, return_all_stages=False):
    stages_outputs = [image]
    for _ in range(stages):
        stages_outputs.append(wavelet2d(stages_outputs[-1]))
    return stages_outputs if return_all_stages else stages_outputs[-1]


def inverse_multi_stage_wavelet2d(image, stages, return_all_stages=False):
    stages_outputs = [image]
    for _ in range(stages):
        stages_outputs.append(inverse_wavelet_2d(stages_outputs[-1]))
    return stages_outputs if return_all_stages else stages_outputs[-1]


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(f'usage:\n{sys.argv[0]} <input_file>')
        exit(1)
    _, input_file = sys.argv

    if input_file == 'test':
        w = h = 32
        cw = ch = h // 32
        template = np.zeros((2 * ch, 2 * cw), dtype=ty)
        template[:ch, :cw] = 254
        template[ch:, cw:] = 254
        image = np.tile(template, (h // ch, w // ch))
    else:
        image = np.array(Image.open(sys.argv[1])).astype(ty)
    image = image

    stages_encode = multi_stage_wavelet2d(image, 3, return_all_stages=True)
    stages_decode = inverse_multi_stage_wavelet2d(stages_encode[-1], 3, return_all_stages=True)

    for i, (a, b) in enumerate(zip(stages_encode, reversed(stages_decode))):
        crop = 16
        a_crop = a[crop:-crop, crop:-crop]
        b_crop = b[crop:-crop, crop:-crop]
        diff = a_crop - b_crop

        print(f"psnr level {i}: {10 * np.log10(256 ** 2 / np.sum(diff ** 2) * diff.size)}")

        plt_image(f"lf diff {i}", diff, cmap="bwr", vmin=-2, vmax=+2)
        plt_image(f"lf enc {i}", a_crop, cmap="gray")
        plt_image(f"lf dec {i}", b_crop, cmap="gray")

        if i == 0:
            diff_values = a_crop[np.where(diff != 0)]
            plt_hist(f"diff hist {i}", diff)
            plt_hist(f"lf hist enc {i}", a_crop)
            plt_hist(f"lf hist dec {i}", b_crop)
    plt_show()