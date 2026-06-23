"""Photo BOL pre-processing: auto-crop perspective + auto-rotate text direction.

Ported with no logic change — the original implementation is solid.
"""
from __future__ import annotations

import logging
from typing import Optional

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


def _order_points(pts: np.ndarray) -> np.ndarray:
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def _four_point_transform(image: np.ndarray, pts: np.ndarray) -> np.ndarray:
    rect = _order_points(pts)
    (tl, tr, br, bl) = rect
    width_a = np.linalg.norm(br - bl)
    width_b = np.linalg.norm(tr - tl)
    max_width = max(int(width_a), int(width_b))
    height_a = np.linalg.norm(tr - br)
    height_b = np.linalg.norm(tl - bl)
    max_height = max(int(height_a), int(height_b))
    if max_width < 10 or max_height < 10:
        return image
    dst = np.array([
        [0, 0],
        [max_width - 1, 0],
        [max_width - 1, max_height - 1],
        [0, max_height - 1],
    ], dtype="float32")
    M = cv2.getPerspectiveTransform(rect, dst)
    return cv2.warpPerspective(image, M, (max_width, max_height))


def _find_document_contour(image: np.ndarray) -> Optional[np.ndarray]:
    h, w = image.shape[:2]
    ratio = 1000.0 / max(h, w) if max(h, w) > 1000 else 1.0
    small = cv2.resize(image, (int(w * ratio), int(h * ratio)))
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    blur = cv2.bilateralFilter(gray, 9, 75, 75)
    edged = cv2.Canny(blur, 30, 100)
    edged = cv2.dilate(edged, np.ones((3, 3), np.uint8), iterations=2)
    edged = cv2.erode(edged, np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(edged.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:5]
    small_area = small.shape[0] * small.shape[1]
    for c in contours:
        area = cv2.contourArea(c)
        if area < small_area * 0.2:
            continue
        peri = cv2.arcLength(c, True)
        for eps_mult in (0.01, 0.02, 0.03, 0.04):
            approx = cv2.approxPolyDP(c, eps_mult * peri, True)
            if len(approx) == 4:
                return (approx.reshape(4, 2) / ratio).astype("float32")
    return None


def auto_crop_document(img: Image.Image) -> Image.Image:
    try:
        cv_img = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)
        contour = _find_document_contour(cv_img)
        if contour is None:
            return img
        warped = _four_point_transform(cv_img, contour)
        warped_rgb = cv2.cvtColor(warped, cv2.COLOR_BGR2RGB)
        return Image.fromarray(warped_rgb)
    except Exception:
        logger.exception("auto_crop_failed")
        return img


def auto_rotate_document(img: Image.Image) -> Image.Image:
    try:
        import pytesseract
        osd = pytesseract.image_to_osd(img, output_type=pytesseract.Output.DICT)
        rotate_by = osd.get("rotate", 0)
        if rotate_by and rotate_by != 0:
            return img.rotate(-rotate_by, expand=True)
    except Exception:
        logger.debug("auto_rotate_skip", exc_info=True)
    return img


def preprocess_for_ocr(img: Image.Image) -> Image.Image:
    """Phase-2 improvement: denoise + contrast boost + adaptive threshold for OCR."""
    try:
        cv_img = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
        # CLAHE: local contrast enhancement
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        gray = clahe.apply(gray)
        # Mild denoise
        denoised = cv2.fastNlMeansDenoising(gray, h=10)
        return Image.fromarray(denoised)
    except Exception:
        logger.debug("ocr_preprocess_skip", exc_info=True)
        return img
