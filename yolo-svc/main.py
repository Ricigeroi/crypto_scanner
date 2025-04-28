import io, base64, numpy as np, os
from flask import Flask, request, jsonify
from PIL import Image, ImageDraw, ImageFont
from ultralytics import YOLO

THR = float(os.getenv("THRESHOLD", 0.45))
model = YOLO("model/model.pt")

label_map = { 0:"Head&Shoulders Bottom", 1:"Head&Shoulders Top",
              2:"M-Head", 3:"StockLine", 4:"Triangle", 5:"W-Bottom" }

app = Flask(__name__)

def run(img_np):
    r = model.predict(img_np, verbose=False)[0]
    return r.boxes.xyxy.cpu().numpy(), r.boxes.conf.cpu().numpy(), r.boxes.cls.cpu().numpy().astype(int)

def draw(img, det, thr):
    boxes, scores, clss = det
    draw = ImageDraw.Draw(img)
    fnt  = ImageFont.load_default()
    for box,s,cls in zip(boxes,scores,clss):
        if s<thr: continue
        x1,y1,x2,y2 = map(int, box)
        label = f"{label_map.get(cls,'cls_'+str(cls))}:{s:.2f}"
        tw, th = fnt.getbbox(label)[2:]
        draw.rectangle([x1, y1-th, x1+tw, y1], fill="red")      # bg
        draw.text((x1,y1-th), label, fill="white", font=fnt)
        draw.rectangle([x1,y1,x2,y2], outline="red", width=3)
    return img

@app.post("/detect")
def detect():
    data = request.get_json(silent=True) or {}
    b64  = data.get("image","").split(",")[-1]
    if not b64: return jsonify(error="field 'image' required"),400
    thr  = float(data.get("thr", THR))
    img  = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
    det  = run(np.array(img))
    vis  = draw(img.copy(), det, thr)
    buff = io.BytesIO(); vis.save(buff, format="JPEG")
    return jsonify(image=f"data:image/jpeg;base64,{base64.b64encode(buff.getvalue()).decode()}")

if __name__ == "__main__":
    app.run(host="0.0.0.0",port=9100)
