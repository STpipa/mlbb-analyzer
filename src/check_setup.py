"""Fase 0: verifica que el entorno esté listo (Tesseract, PIL, OpenCV, resto de libs)."""
import shutil
import subprocess
import sys

from PIL import Image
import cv2
import numpy as np
import pytesseract
import imagehash
import pandas
import openpyxl


def check_tesseract_binary():
    path = shutil.which("tesseract")
    if not path:
        raise RuntimeError("tesseract no está en el PATH")
    version = subprocess.run(
        ["tesseract", "--version"], capture_output=True, text=True, check=True
    ).stdout.splitlines()[0]
    print(f"OK tesseract binario: {path} ({version})")


def check_pil_and_opencv():
    img = Image.new("RGB", (100, 100), color=(0, 128, 255))
    arr = np.array(img)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    assert gray.shape == (100, 100)
    print(f"OK PIL crea imágenes ({img.size}) y OpenCV las procesa (shape={gray.shape})")


def check_pytesseract():
    print(f"OK pytesseract importado, apunta a: {pytesseract.pytesseract.tesseract_cmd}")


def check_imagehash():
    img = Image.new("RGB", (64, 64), color=(200, 50, 50))
    h = imagehash.phash(img)
    print(f"OK imagehash.phash funciona: {h}")


def check_pandas_openpyxl():
    print(f"OK pandas {pandas.__version__}, openpyxl {openpyxl.__version__}")


if __name__ == "__main__":
    print(f"Python: {sys.version}\n")
    check_tesseract_binary()
    check_pil_and_opencv()
    check_pytesseract()
    check_imagehash()
    check_pandas_openpyxl()
    print("\nFase 0 completa: entorno listo.")
