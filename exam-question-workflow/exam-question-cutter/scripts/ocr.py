#!/usr/bin/env python3
"""
模块2: OCR 文字识别
对每页 PNG 做 OCR, 输出统一格式的 JSON。

输出格式 (每页一个 ocr_page_XX.json):
{
  "ocr_result": [
    {"content": "文字", "top_left_x": 190, "top_left_y": 151,
     "bottom_right_x": 1053, "bottom_right_y": 180},
    ...
  ]
}

用法:
    python3 ocr.py <png_dir> <output_dir> [--backend auto]
    python3 ocr.py <png_dir> <output_dir> --backend precomputed --precomputed-dir <dir>

后端优先级 (auto 模式):
    1. 若 output_dir 中已有 ocr_page_XX.json 则跳过 (增量)
    2. paddleocr (若已安装)
    3. easyocr (若已安装)
    4. tesseract (若已安装)
    5. 报错提示
"""
import argparse
import json
import sys
from pathlib import Path


def _normalize_box(box) -> dict:
    """将各种 OCR 后端的框坐标统一为 {top_left_x, top_left_y, bottom_right_x, bottom_right_y}。"""
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    return {
        "top_left_x": int(min(xs)),
        "top_left_y": int(min(ys)),
        "bottom_right_x": int(max(xs)),
        "bottom_right_y": int(max(ys)),
    }


def get_paddleocr():
    """创建(或复用) PaddleOCR 引擎。单例复用避免每页重载模型(提速 5~10 倍)。"""
    import os
    import paddleocr
    from paddleocr import PaddleOCR
    # 禁用 oneDNN/MKLDNN: 规避 Paddle 3.x 在 CPU 上 PP-OCRv6 的算子兼容问题
    os.environ.setdefault("FLAGS_use_mkldnn", "0")
    major = int(paddleocr.__version__.split(".")[0])
    if major >= 3:
        ocr = PaddleOCR(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            enable_mkldnn=False,
            lang="ch",
        )
    else:
        ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
    return ocr, major


def ocr_paddleocr(img_path: str, ocr=None, major: int | None = None) -> list[dict]:
    """兼容 PaddleOCR 2.x 与 3.x。3.x 用 predict() 接口, 2.x 用旧 ocr() 接口。
    ocr/major 传入复用实例时不再重建(见 run_ocr 的单例优化)。"""
    if ocr is None or major is None:
        ocr, major = get_paddleocr()
    if major >= 3:
        res = ocr.predict(str(img_path))
        items = []
        for r in res:
            # 兼容 Result 对象的属性访问与 dict 访问
            try:
                texts = r["rec_texts"] if "rec_texts" in r else getattr(r, "rec_texts", None)
                polys = r["dt_polys"] if "dt_polys" in r else getattr(r, "dt_polys", None)
            except Exception:
                texts = getattr(r, "rec_texts", None)
                polys = getattr(r, "dt_polys", None)
            texts = texts or []
            polys = polys or []
            for txt, poly in zip(texts, polys):
                items.append({"content": txt, **_normalize_box(poly)})
        return items
    # 2.x 旧接口
    result = ocr.ocr(img_path, cls=True)
    items = []
    for line in result[0]:
        box, (text, conf) = line
        items.append({"content": text, **_normalize_box(box)})
    return items


def ocr_easyocr(img_path: str) -> list[dict]:
    import easyocr
    reader = easyocr.Reader(["ch_sim", "en"], gpu=False)
    result = reader.readtext(img_path)
    items = []
    for box, text, conf in result:
        items.append({"content": text, **_normalize_box(box)})
    return items


def ocr_tesseract(img_path: str) -> list[dict]:
    import pytesseract
    from PIL import Image
    data = pytesseract.image_to_data(Image.open(img_path), lang="chi_sim+eng",
                                     output_type=pytesseract.Output.DICT)
    items = []
    for i, text in enumerate(data["text"]):
        if not text.strip():
            continue
        items.append({
            "content": text.strip(),
            "top_left_x": int(data["left"][i]),
            "top_left_y": int(data["top"][i]),
            "bottom_right_x": int(data["left"][i] + data["width"][i]),
            "bottom_right_y": int(data["top"][i] + data["height"][i]),
        })
    return items


BACKENDS = {
    "paddleocr": ocr_paddleocr,
    "easyocr": ocr_easyocr,
    "tesseract": ocr_tesseract,
}


def detect_backend() -> str | None:
    """自动检测可用的 OCR 后端。"""
    for name in ["paddleocr", "easyocr", "tesseract"]:
        try:
            if name == "paddleocr":
                import paddleocr  # noqa
            elif name == "easyocr":
                import easyocr  # noqa
            elif name == "tesseract":
                import pytesseract  # noqa
            return name
        except ImportError:
            continue
    return None


def run_ocr(png_dir: str, output_dir: str, backend: str = "auto",
            precomputed_dir: str | None = None) -> list[str]:
    """对目录中所有 page_XX.png 做 OCR, 返回输出 JSON 路径列表。"""
    png_dir = Path(png_dir)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    pngs = sorted(png_dir.glob("page_*.png"))
    if not pngs:
        print(f"[ERROR] {png_dir} 中没有 page_*.png", file=sys.stderr)
        sys.exit(1)

    # 预计算结果模式: 直接复制
    if backend == "precomputed":
        if not precomputed_dir:
            print("[ERROR] --backend precomputed 需要 --precomputed-dir", file=sys.stderr)
            sys.exit(1)
        src = Path(precomputed_dir)
        outputs = []
        for png in pngs:
            idx = png.stem.split("_")[1]
            src_file = src / f"ocr_page_{idx}.json"
            dst_file = out / f"ocr_page_{idx}.json"
            if src_file.exists():
                import shutil
                shutil.copy2(src_file, dst_file)
                outputs.append(str(dst_file))
                print(f"  copied {src_file.name}")
            else:
                print(f"  [WARN] 未找到 {src_file.name}, 跳过")
        return outputs

    # 自动检测后端
    if backend == "auto":
        backend = detect_backend()
        if backend is None:
            print("[ERROR] 未检测到可用 OCR 后端 (paddleocr/easyocr/tesseract)。\n"
                  "  请安装其一: pip install paddleocr / easyocr / pytesseract\n"
                  "  或使用 --backend precomputed 提供已有 OCR 结果。", file=sys.stderr)
            sys.exit(1)
        print(f"[OCR] 使用后端: {backend}")

    ocr_fn = BACKENDS[backend]
    outputs = []
    # PaddleOCR: 单例复用引擎(模型只加载一次), 避免每页重建
    paddle_engine = None
    paddle_major = None
    if backend == "paddleocr":
        paddle_engine, paddle_major = get_paddleocr()
    for png in pngs:
        idx = png.stem.split("_")[1]
        out_file = out / f"ocr_page_{idx}.json"
        if out_file.exists():
            print(f"  skip {png.name} (已有 {out_file.name})")
            outputs.append(str(out_file))
            continue
        print(f"  ocr {png.name} ...", end=" ", flush=True)
        if backend == "paddleocr":
            items = ocr_paddleocr(str(png), paddle_engine, paddle_major)
        else:
            items = ocr_fn(str(png))
        items.sort(key=lambda r: (r["top_left_y"], r["top_left_x"]))
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump({"ocr_result": items}, f, ensure_ascii=False, indent=2)
        print(f"{len(items)} items -> {out_file.name}")
        outputs.append(str(out_file))
    return outputs


def main():
    ap = argparse.ArgumentParser(description="试卷 OCR")
    ap.add_argument("png_dir", help="page_*.png 所在目录")
    ap.add_argument("output_dir", help="OCR JSON 输出目录")
    ap.add_argument("--backend", default="auto",
                    choices=["auto", "paddleocr", "easyocr", "tesseract", "precomputed"])
    ap.add_argument("--precomputed-dir", help="预计算 OCR JSON 所在目录 (backend=precomputed 时使用)")
    args = ap.parse_args()
    outputs = run_ocr(args.png_dir, args.output_dir, args.backend, args.precomputed_dir)
    print(f"\nDone: {len(outputs)} pages -> {args.output_dir}")


if __name__ == "__main__":
    main()
