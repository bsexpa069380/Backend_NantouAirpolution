from flask import Flask, request, jsonify,render_template,  redirect, url_for
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
import bcrypt
import os
from dotenv import load_dotenv
import jwt
import datetime
from functools import wraps
from r2_utils import r2_upload_file, r2_delete_file,r2_client
from db_init import db_init, get_db_connection , db_reset
import json

app = Flask(__name__)
CORS(app)

load_dotenv()
r2_client()
# PostgreSQL 資料庫連線設定




# 登入區塊



@app.route("/")
def root():
    return redirect(url_for("login"))

@app.route("/login")
def login():
    return render_template("login.html")



JWT_SECRET = os.getenv("JWT_SECRET", "fallback_secret")
JWT_EXPIRE_SECONDS = int(os.getenv("JWT_EXPIRE_SECONDS", "3600"))

@app.post("/api/login")
def login_api():
    conn = None
    cur = None

    try:
        data = request.get_json()
        username = data.get("username")
        password = data.get("password")

        if not username or not password:
            return jsonify(message="請提供帳號與密碼"), 400

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT password_hash FROM users WHERE username = %s", (username,))
        row = cur.fetchone()

        if row:
            stored_hash = row[0]
            if bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8")):
                payload = {
                    "username": username,
                    "exp": datetime.datetime.utcnow() + datetime.timedelta(seconds=JWT_EXPIRE_SECONDS)
                }
                token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
                return jsonify(message="登入成功", token=token), 200
            else:
                return jsonify(message="帳號或密碼錯誤"), 401
        else:
            return jsonify(message="帳號或密碼錯誤"), 401

    except Exception as e:
        print("[❌] Login error:", e)
        return jsonify(message="伺服器錯誤"), 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

def jwt_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.headers.get('Authorization')
        if token is None or not token.startswith("Bearer "):
            return jsonify({"error": "未提供 token"}), 401

        try:
            token_value = token.split(" ")[1]
            decoded = jwt.decode(token_value, JWT_SECRET, algorithms=["HS256"])
            # 可選：把解碼資料放入 request context，例如 request.user = decoded
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token 已過期"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Token 無效"}), 401

        return f(*args, **kwargs)
    return decorated_function



## ---------------------------------空氣凈化區 區塊 -------------------------------------------##

# ✅ 取得所有空氣淨化區
@app.get("/api/purification_zones")
def get_all_zones():
    year = request.args.get("year")
    district = request.args.get("district")

    sql = "SELECT * FROM purification_zones WHERE 1=1"
    params = []

    if year:
        sql += " AND year = %s"
        params.append(year)
    if district:
        sql += " AND district = %s"
        params.append(district)

    sql += " ORDER BY created_at DESC"
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        return jsonify(rows), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()


# ✅ 取得單一資料
@app.get("/api/purification_zones/<int:id>")
def get_zone(id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute("SELECT * FROM purification_zones WHERE id = %s;", (id,))
        row = cursor.fetchone()

        if row:
            if row.get("image_urls"):
                if isinstance(row["image_urls"], str):
                    row["image_urls"] = json.loads(row["image_urls"])
            return jsonify(row), 200
        else:
            return jsonify({"error": "Not found"}), 404

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()

# ✅ 新增資料
@app.post("/api/purification_zones")
@jwt_required
def create_zone():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # 取得圖片（若有上傳）
        images = request.files.getlist("images")
        image_urls = []

        for img in images:
            if img and img.filename:
                url = r2_upload_file(img, folder="purification_zones")
                if url:
                    image_urls.append(url)
        # 取得表單欄位資料

        image_urls_value = json.dumps(image_urls) if image_urls else None
        data = request.form

        cursor.execute("""
            INSERT INTO purification_zones (
                serial, year, district, type, project_name,
                maintain_unit, adopt_unit, area, length, maintain_start_date,
                maintain_end_date, gps,annotation,
                subsidy_source, image_urls
            ) VALUES (%s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s
                      )
            RETURNING *;
        """, (
            data.get("serial"),
            data.get("year"),
            data.get("district"),
            data.get("type"),
            data.get("project_name"),
            data.get("maintain_unit"),
            data.get("adopt_unit"),
            data.get("area"),
            data.get("length"),
            data.get("maintain_start_date")or None,
            data.get("maintain_end_date")or None,
            data.get("gps"),
            data.get("annotation"),
            data.get("subsidy_source"),
        
            image_urls_value
        ))

        new_record = cursor.fetchone()
        conn.commit()
        return jsonify(new_record), 201

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()


# ✅ 修改資料
@app.put("/api/purification_zones/<int:id>")
@jwt_required
def update_zone(id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        form = request.form
        files = request.files

        # ✅ Step 1: Get existing images that user decided to keep
        existing_images = form.getlist("existing_images")  # frontend must send this as hidden inputs or FormData
        image_urls = existing_images[:]  # start with these

        # ✅ Step 2: Handle new uploads
        new_files = request.files.getlist("images")
        for img in new_files:
            if img and img.filename:
                url = r2_upload_file(img, folder="purification_zones")
                if url:
                    image_urls.append(url)

        # ✅ Step 3: Convert to JSON for Postgres JSONB
        image_urls_value = json.dumps(image_urls) if image_urls else None

        cursor.execute("""
            UPDATE purification_zones SET
                serial = %s,
                year = %s,
                district = %s,
                type = %s,
                project_name = %s,
                maintain_unit = %s,
                adopt_unit = %s,
                area = %s,
                length = %s,
                maintain_start_date = %s,
                maintain_end_date = %s,
                gps = %s,
                subsidy_source = %s,
                annotation = %s,
                image_urls = %s
            WHERE id = %s
            RETURNING *;
        """, (
            form.get("serial"),
            form.get("year"),
            form.get("district"),
            form.get("type"),
            form.get("project_name"),
            form.get("maintain_unit"),
            form.get("adopt_unit"),
            form.get("area"),
            form.get("length"),
            form.get("maintain_start_date")or None,
            form.get("maintain_end_date")or None,
            form.get("gps"),
            form.get("subsidy_source"),
            form.get("annotation"),
            image_urls_value,
            id
        ))

        updated = cursor.fetchone()
        conn.commit()
        return jsonify(updated), 200 if updated else (jsonify({"error": "ID not found"}), 404)

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()


# ✅ 刪除資料
@app.delete("/api/purification_zones/<int:id>")
@jwt_required
def delete_zone(id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)  # ✅ use dict-like rows

    try:
        # Step 1: Fetch the record first (to get image_urls)
        cursor.execute("SELECT image_urls FROM purification_zones WHERE id = %s;", (id,))
        record = cursor.fetchone()

        if not record:
            return jsonify({"error": "ID not found"}), 404

        # Parse JSONB into Python list
        image_urls = []
        if record["image_urls"]:
            if isinstance(record["image_urls"], str):  # JSON string
                image_urls = json.loads(record["image_urls"])
            elif isinstance(record["image_urls"], list):  # already list
                image_urls = record["image_urls"]

        # Step 2: Delete DB row
        cursor.execute("DELETE FROM purification_zones WHERE id = %s RETURNING *;", (id,))
        deleted = cursor.fetchone()
        conn.commit()

        # Step 3: Delete images from R2
        for url in image_urls:
            r2_delete_file(url)

        return jsonify({
            "deleted": deleted,
            "images_deleted": image_urls
        }), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()

@app.route("/api/purification_zones/visibility", methods=["GET"])
def get_visibility():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute("SELECT * FROM settings WHERE section = %s;", ('greenifications',))
        state = cursor.fetchone()
        if state:
            return jsonify({"visible": state['visible']})
        else:
            return jsonify({"error": "Section not found"}), 404
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()

@app.route("/api/purification_zones/visibility", methods=["PUT"])
@jwt_required
def update_visibility():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        data = request.get_json()
        visible = data.get("visible", True)

        cursor.execute("UPDATE settings SET visible = %s WHERE section = %s RETURNING *;", (visible, 'greenifications'))
        state = cursor.fetchone()
        conn.commit()

        if state:
            return jsonify({"success": True, "visible": state['visible']})
        else:
            return jsonify({"error": "Section not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()


## ---------------------------------空氣綠牆區 區塊 -------------------------------------------##

# ✅ 取得所有空氣綠牆區
@app.get("/api/green_walls")
def get_all_greenWalls():
    year = request.args.get("year")
    district = request.args.get("district")

    sql = "SELECT * FROM green_walls WHERE 1=1"
    params = []

    if year:
        sql += " AND year = %s"
        params.append(year)
    if district:
        sql += " AND district = %s"
        params.append(district)

    sql += " ORDER BY created_at DESC"
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        return jsonify(rows), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()


# ✅ 取得單一資料
@app.get("/api/green_walls/<int:id>")
def get_greenWall(id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute("SELECT * FROM green_walls WHERE id = %s;", (id,))
        row = cursor.fetchone()

        if row:
            if row.get("image_urls"):
                if isinstance(row["image_urls"], str):
                    row["image_urls"] = json.loads(row["image_urls"])
            return jsonify(row), 200
        else:
            return jsonify({"error": "Not found"}), 404

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()


# ✅ 新增資料
@app.post("/api/green_walls")
@jwt_required
def create_greenWall():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # 取得圖片（若有上傳）
        images = request.files.getlist("images")
        image_urls = []

        for img in images:
            if img and img.filename:
                url = r2_upload_file(img, folder="green_walls")
                if url:
                    image_urls.append(url)
        # 取得表單欄位資料

        image_urls_value = json.dumps(image_urls) if image_urls else None
        data = request.form

        cursor.execute("""
            INSERT INTO green_walls (
                serial, year, district, type, project_name,
                maintain_unit, adopt_unit, area, length, maintain_start_date,
                maintain_end_date, gps,annotation,
                subsidy_source, image_urls
            ) VALUES (%s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s
                      )
            RETURNING *;
        """, (
            data.get("serial"),
            data.get("year"),
            data.get("district"),
            data.get("type"),
            data.get("project_name"),
            data.get("maintain_unit"),
            data.get("adopt_unit"),
            data.get("area"),
            data.get("length"),
            data.get("maintain_start_date")or None,
            data.get("maintain_end_date")or None,
            data.get("gps"),
            data.get("annotation"),
            data.get("subsidy_source"),
        
            image_urls_value
        ))

        new_record = cursor.fetchone()
        conn.commit()
        return jsonify(new_record), 201

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()


# ✅ 修改資料
@app.route("/api/green_walls/<int:id>", methods=["PUT"])
@jwt_required
def update_greenWall(id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        form = request.form
        files = request.files

        # ✅ Step 1: Get existing images that user decided to keep
        existing_images = form.getlist("existing_images")  # frontend must send this as hidden inputs or FormData
        image_urls = existing_images[:]  # start with these

        # ✅ Step 2: Handle new uploads
        new_files = request.files.getlist("images")
        for img in new_files:
            if img and img.filename:
                url = r2_upload_file(img, folder="green_walls")
                if url:
                    image_urls.append(url)

        # ✅ Step 3: Convert to JSON for Postgres JSONB
        image_urls_value = json.dumps(image_urls) if image_urls else None

        cursor.execute("""
            UPDATE green_walls SET
                serial = %s,
                year = %s,
                district = %s,
                type = %s,
                project_name = %s,
                maintain_unit = %s,
                adopt_unit = %s,
                area = %s,
                length = %s,
                maintain_start_date = %s,
                maintain_end_date = %s,
                gps = %s,
                subsidy_source = %s,
                annotation = %s,
                image_urls = %s
            WHERE id = %s
            RETURNING *;
        """, (
            form.get("serial"),
            form.get("year"),
            form.get("district"),
            form.get("type"),
            form.get("project_name"),
            form.get("maintain_unit"),
            form.get("adopt_unit"),
            form.get("area"),
            form.get("length"),
            form.get("maintain_start_date") or None,
            form.get("maintain_end_date") or None,
            form.get("gps"),
            form.get("subsidy_source"),
            form.get("annotation"),
            image_urls_value,
            id
        ))

        updated = cursor.fetchone()
        conn.commit()
        return jsonify(updated), 200 if updated else (jsonify({"error": "ID not found"}), 404)

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()

# ✅ 刪除資料
@app.delete("/api/green_walls/<int:id>")
@jwt_required
def delete_greenWall(id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)  # ✅ use dict-like rows

    try:
        # Step 1: Fetch the record first (to get image_urls)
        cursor.execute("SELECT image_urls FROM green_walls WHERE id = %s;", (id,))
        record = cursor.fetchone()

        if not record:
            return jsonify({"error": "ID not found"}), 404

        # Parse JSONB into Python list
        image_urls = []
        if record["image_urls"]:
            if isinstance(record["image_urls"], str):  # JSON string
                image_urls = json.loads(record["image_urls"])
            elif isinstance(record["image_urls"], list):  # already list
                image_urls = record["image_urls"]

        # Step 2: Delete DB row
        cursor.execute("DELETE FROM green_walls WHERE id = %s RETURNING *;", (id,))
        deleted = cursor.fetchone()
        conn.commit()

        # Step 3: Delete images from R2
        for url in image_urls:
            r2_delete_file(url)

        return jsonify({
            "deleted": deleted,
            "images_deleted": image_urls
        }), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()

## ---------------------------------綠美化 區塊 -------------------------------------------##

# ✅ 取得所有綠美化
@app.get("/api/greenifications")
def get_all_greenifications():
    year = request.args.get("year")
    district = request.args.get("district")

    sql = "SELECT * FROM greenifications WHERE 1=1"
    params = []

    if year:
        sql += " AND year = %s"
        params.append(year)
    if district:
        sql += " AND district = %s"
        params.append(district)

    sql += " ORDER BY created_at DESC"
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        return jsonify(rows), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()


# ✅ 取得單一資料
@app.get("/api/greenifications/<int:id>")
def get_greenification(id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute("SELECT * FROM greenifications WHERE id = %s;", (id,))
        row = cursor.fetchone()

        if row:
            if row.get("image_urls"):
                if isinstance(row["image_urls"], str):
                    row["image_urls"] = json.loads(row["image_urls"])
            return jsonify(row), 200
        else:
            return jsonify({"error": "Not found"}), 404

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()

# ✅ 新增資料
@app.post("/api/greenifications")
@jwt_required
def create_greenification():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # 取得圖片（若有上傳）
        images = request.files.getlist("images")
        image_urls = []

        for img in images:
            if img and img.filename:
                url = r2_upload_file(img, folder="greenifications")
                if url:
                    image_urls.append(url)
        # 取得表單欄位資料

        image_urls_value = json.dumps(image_urls) if image_urls else None
        data = request.form

        cursor.execute("""
            INSERT INTO greenifications (
                serial, year, district, type, project_name,
                maintain_unit, adopt_unit, area, length, maintain_start_date,
                maintain_end_date, gps,annotation,
                subsidy_source, image_urls
            ) VALUES (%s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s
                      )
            RETURNING *;
        """, (
            data.get("serial"),
            data.get("year"),
            data.get("district"),
            data.get("type"),
            data.get("project_name"),
            data.get("maintain_unit"),
            data.get("adopt_unit"),
            data.get("area"),
            data.get("length"),
            data.get("maintain_start_date")or None,
            data.get("maintain_end_date")or None,
            data.get("gps"),
            data.get("annotation"),
            data.get("subsidy_source"),
        
            image_urls_value
        ))

        new_record = cursor.fetchone()
        conn.commit()
        return jsonify(new_record), 201

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()


# ✅ 修改資料
@app.put("/api/greenifications/<int:id>")
@jwt_required
def update_greenification(id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        form = request.form
        files = request.files

        # ✅ Step 1: Get existing images that user decided to keep
        existing_images = form.getlist("existing_images")  # frontend must send this as hidden inputs or FormData
        image_urls = existing_images[:]  # start with these

        # ✅ Step 2: Handle new uploads
        new_files = request.files.getlist("images")
        for img in new_files:
            if img and img.filename:
                url = r2_upload_file(img, folder="green_walls")
                if url:
                    image_urls.append(url)

        # ✅ Step 3: Convert to JSON for Postgres JSONB
        image_urls_value = json.dumps(image_urls) if image_urls else None

        cursor.execute("""
            UPDATE greenifications SET
                serial = %s,
                year = %s,
                district = %s,
                type = %s,
                project_name = %s,
                maintain_unit = %s,
                adopt_unit = %s,
                area = %s,
                length = %s,
                maintain_start_date = %s,
                maintain_end_date = %s,
                gps = %s,
                subsidy_source = %s,
                annotation = %s,
                image_urls = %s
            WHERE id = %s
            RETURNING *;
        """, (
            form.get("serial"),
            form.get("year"),
            form.get("district"),
            form.get("type"),
            form.get("project_name"),
            form.get("maintain_unit"),
            form.get("adopt_unit"),
            form.get("area"),
            form.get("length"),
            form.get("maintain_start_date")or None,
            form.get("maintain_end_date")or None,
            form.get("gps"),
            form.get("subsidy_source"),
            form.get("annotation"),
            image_urls_value,
            id
        ))

        updated = cursor.fetchone()
        conn.commit()
        if updated:
            return jsonify(updated), 200
        else:
            return jsonify({"error": "ID not found"}), 404

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()


# ✅ 刪除資料
@app.delete("/api/greenifications/<int:id>")
@jwt_required
def delete_greenification(id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)  # ✅ use dict-like rows

    try:
        # Step 1: Fetch the record first (to get image_urls)
        cursor.execute("SELECT image_urls FROM greenifications WHERE id = %s;", (id,))
        record = cursor.fetchone()

        if not record:
            return jsonify({"error": "ID not found"}), 404

        # Parse JSONB into Python list
        image_urls = []
        if record["image_urls"]:
            if isinstance(record["image_urls"], str):  # JSON string
                image_urls = json.loads(record["image_urls"])
            elif isinstance(record["image_urls"], list):  # already list
                image_urls = record["image_urls"]

        # Step 2: Delete DB row
        cursor.execute("DELETE FROM greenifications WHERE id = %s RETURNING *;", (id,))
        deleted = cursor.fetchone()
        conn.commit()

        # Step 3: Delete images from R2
        for url in image_urls:
            r2_delete_file(url)

        return jsonify({
            "deleted": deleted,
            "images_deleted": image_urls
        }), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()

    
## ---------------------------------樹種介紹  ------------------------------------------
@app.post("/api/tree_intros")
@jwt_required
def create_tree_intro():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        image = request.files.get("image")
        image_url = None

        if image and image.filename:
            url = r2_upload_file(image, folder="tree_intros")
            if url:
                image_url = url

        # 取得表單欄位資料 
        data = request.form

        cursor.execute("""
            INSERT INTO tree_intros (title, scientific_name ,plant_phenology,features,
            natural_distribution, usage, other_usage, breeding_intro, source,  image_url)
            VALUES (%s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s)
            RETURNING *;
        """, (
            data.get("title"),
            data.get("scientific_name"),
            data.get("plant_phenology"),
            data.get("features"),
            data.get("natural_distribution"),
            data.get("usage"),
            data.get("other_usage"),
            data.get("breeding_intro"),
            data.get("source"),
            image_url
        ))

        new_data = cursor.fetchone()
        conn.commit()
        return jsonify(new_data), 201

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()

@app.get("/api/tree_intros")
def get_tree_intros():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute("SELECT * FROM tree_intros ORDER BY id DESC;")
        data = cursor.fetchall()
        return jsonify(data)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()
@app.get("/api/tree_intros/<int:id>")
def get_tree_intro(id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute("SELECT * FROM tree_intros WHERE id = %s;", (id,))
        row = cursor.fetchone()
        if row:
            # ✅ For single image, just return as-is
            # row["image_url"] will already be a string (or None)
            return jsonify(row), 200
        else:
            return jsonify({"error": "找不到資料"}), 404
        
        

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()
@app.put("/api/tree_intros/<int:id>")
def update_tree_intro(id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        data = request.form
        image = request.files.get("image")
        image_url = None

        # ✅ Upload to R2 if a new image is provided
        if image and image.filename:
            image_url = r2_upload_file(image, folder="tree_intros")

        cursor.execute("""
            UPDATE tree_intros
            SET title = %s,
                scientific_name = %s,
                plant_phenology = %s,
                features = %s,
                natural_distribution = %s,
                usage = %s,
                other_usage = %s,
                breeding_intro = %s,
                source = %s,
                image_url = COALESCE(%s, image_url)
            WHERE id = %s
            RETURNING *;
        """, (
            data.get("title"),
            data.get("scientific_name"),
            data.get("plant_phenology"),
            data.get("features"),
            data.get("natural_distribution"),
            data.get("usage"),
            data.get("other_usage"),
            data.get("breeding_intro"),
            data.get("source"),
            image_url,  # new R2 url or None → keep old if None
            id
        ))

        updated = cursor.fetchone()
        conn.commit()

        if updated:
            return jsonify(updated), 200
        else:
            return jsonify({"error": "ID 不存在"}), 404

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()
@app.delete("/api/tree_intros/<int:id>")
def delete_tree_intro(id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)  # ✅ so we can use dict access

    try:
        # ✅ Step 1: Fetch the record first
        cursor.execute("SELECT image_url FROM tree_intros WHERE id = %s;", (id,))
        record = cursor.fetchone()

        if not record:
            return jsonify({"error": "ID 不存在"}), 404

        image_url = record.get("image_url")

        # ✅ Step 2: Delete DB row
        cursor.execute("DELETE FROM tree_intros WHERE id = %s RETURNING id;", (id,))
        deleted = cursor.fetchone()
        conn.commit()

        # ✅ Step 3: Clean up R2 if image exists
        if image_url:
            r2_delete_file(image_url)

        return jsonify({
            "message": "刪除成功",
            "deleted_id": deleted["id"],
            "deleted_image": image_url
        }), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()


## ---------------------------- Result 成果後台 API -----------------------------

@app.post("/api/result")
@jwt_required
def create_result():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        image = request.files.get("image")
        image_url = None

        if image and image.filename:
            url = r2_upload_file(image, folder="results")
            if url:
                image_url = url

        # 取得表單欄位資料 
        data = request.form

        cursor.execute("""
            INSERT INTO result (title, date, content, image_url)
            VALUES (%s, %s, %s, %s)
            RETURNING *;
        """, (
            data.get("title"),
            data.get("date"),
            data.get("content"),
            image_url
        ))

        new_data = cursor.fetchone()
        conn.commit()
        return jsonify(new_data), 201

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()


@app.get("/api/result")
def get_results():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute("SELECT * FROM result ORDER BY id DESC;")
        data = cursor.fetchall()
        return jsonify(data)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()
@app.get("/api/result/<int:id>")
def get_result(id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute("SELECT * FROM result WHERE id = %s;", (id,))
        row = cursor.fetchone()
        if row:
            # ✅ For single image, just return as-is
            # row["image_url"] will already be a string (or None)
            return jsonify(row), 200
        else:
            return jsonify({"error": "找不到資料"}), 404
        
        

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()
    
@app.put("/api/result/<int:id>")
def update_result_intro(id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        data = request.form
        image = request.files.get("image")
        image_url = None

        # ✅ Upload to R2 if a new image is provided
        if image and image.filename:
            image_url = r2_upload_file(image, folder="results")

        cursor.execute("""
            UPDATE result
            SET title = %s,
                date = %s,
                content = %s,
                image_url = COALESCE(%s, image_url)
            WHERE id = %s
            RETURNING *;
        """, (
            data.get("title"),
            data.get("date"),
            data.get("content"),
            image_url,  # new R2 url or None → keep old if None
            id
        ))

        updated = cursor.fetchone()
        conn.commit()

        if updated:
            return jsonify(updated), 200
        else:
            return jsonify({"error": "ID 不存在"}), 404

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()
    
@app.delete("/api/result/<int:id>")
def delete_result(id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)  # ✅ so we can use dict access

    try:
        # ✅ Step 1: Fetch the record first
        cursor.execute("SELECT image_url FROM result WHERE id = %s;", (id,))
        record = cursor.fetchone()

        if not record:
            return jsonify({"error": "ID 不存在"}), 404

        image_url = record.get("image_url")

        # ✅ Step 2: Delete DB row
        cursor.execute("DELETE FROM result WHERE id = %s RETURNING id;", (id,))
        deleted = cursor.fetchone()
        conn.commit()

        # ✅ Step 3: Clean up R2 if image exists
        if image_url:
            r2_delete_file(image_url)

        return jsonify({
            "message": "刪除成功",
            "deleted_id": deleted["id"],
            "deleted_image": image_url
        }), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()

# ---------------------------- File 檔案後台 API -----------------------------

@app.post("/api/file")
@jwt_required
def create_file():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        file = request.files.get("file")
        file_url = None

        if file and file.filename:
            url = r2_upload_file(file, folder="files")
            if url:
                file_url = url

        # 取得表單欄位資料 
        data = request.form

        cursor.execute("""
            INSERT INTO files (title, date, note, file_url)
            VALUES (%s, %s, %s, %s)
            RETURNING *;
        """, (
            data.get("title"),
            data.get("date"),
            data.get("note"),
            file_url
        ))

        new_data = cursor.fetchone()
        conn.commit()
        return jsonify(new_data), 201

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()
@app.get("/api/file")
def get_files():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute("SELECT * FROM files ORDER BY id DESC;")
        data = cursor.fetchall()
        return jsonify(data)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()
@app.get("/api/file/<int:id>")
def get_file(id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute("SELECT * FROM files WHERE id = %s;", (id,))
        row = cursor.fetchone()
        if row:
            # ✅ For single file, just return as-is
            # row["file_url"] will already be a string (or None)
            return jsonify(row), 200
        else:
            return jsonify({"error": "找不到資料"}), 404
    

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()
@app.put("/api/file/<int:id>")
def update_file_intro(id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        data = request.form
        file = request.files.get("file")
        file_url = None

        # ✅ Upload to R2 if a new file is provided
        if file and file.filename:
            file_url = r2_upload_file(file, folder="files")

        cursor.execute("""
            UPDATE files
            SET title = %s,
                date = %s,
                note = %s,
                file_url = COALESCE(%s, file_url)
            WHERE id = %s
            RETURNING *;
        """, (
            data.get("title"),
            data.get("date"),
            data.get("note"),
            file_url,  # new R2 url or None → keep old if None
            id
        ))

        updated = cursor.fetchone()
        conn.commit()

        if updated:
            return jsonify(updated), 200
        else:
            return jsonify({"error": "ID 不存在"}), 404

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()
@app.delete("/api/file/<int:id>")
def delete_file(id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)  # ✅ so we can use dict access

    try:
        # ✅ Step 1: Fetch the record first
        cursor.execute("SELECT file_url FROM files WHERE id = %s;", (id,))
        record = cursor.fetchone()

        if not record:
            return jsonify({"error": "ID 不存在"}), 404

        file_url = record.get("file_url")

        # ✅ Step 2: Delete DB row
        cursor.execute("DELETE FROM files WHERE id = %s RETURNING id;", (id,))
        deleted = cursor.fetchone()
        conn.commit()

        # ✅ Step 3: Clean up R2 if file exists
        if file_url:
            r2_delete_file(file_url)

        return jsonify({
            "message": "刪除成功",
            "deleted_id": deleted["id"],
            "deleted_file": file_url
        }), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()
### --------------------------------- AREA ARRGEGATION -------------------------------------------##



@app.route("/api/summary", methods=["GET"])
def get_summary():
    table = request.args.get("table", "").strip()
    district = request.args.get("district", "default").strip()

    # ✅ allow only known tables (to prevent SQL injection)
    valid_tables = ["greenifications", "green_walls", "purification_zones"]
    if table not in valid_tables:
        return jsonify({"error": "Invalid table"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    # build WHERE clause
    where_clause = ""
    params = {}
    if district != "default":
        where_clause = "WHERE district = %(district)s"
        params["district"] = district

    query = f"""
        SELECT COUNT(*)::int,
               COALESCE(SUM(area),0)::int,
               COALESCE(SUM(length),0)::int
        FROM {table} {where_clause}
    """

    cursor.execute(query, params)
    c, a, l = cursor.fetchone()

    cursor.close()
    conn.close()

    return jsonify({
        "table": table,
        "district": district,
        "count": c,
        "area": a,
        "length": l
    })

    ### --------------------------------- HIDE & SHOW SECTION -------------------------------------------##

ALLOWED_KEYS = {'purification', 'green_wall', 'greenification'}

@app.get("/api/site/sections")
def api_get_sections():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT key, label, is_visible FROM site_sections ORDER BY label;")
        return jsonify(cur.fetchall()), 200
    finally:
        cur.close(); conn.close()

@app.patch("/api/site/sections/<key>")
def api_patch_section(key):
    if key not in ALLOWED_KEYS:
        return jsonify({"error": "invalid key"}), 400

    payload = request.get_json(silent=True) or {}
    if "is_visible" not in payload:
        return jsonify({"error": "missing is_visible"}), 400

    is_visible = bool(payload["is_visible"])

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
          UPDATE site_sections
             SET is_visible = %s
           WHERE key = %s
       RETURNING key, label, is_visible;
        """, (is_visible, key))
        row = cur.fetchone()
        conn.commit()
        if not row:
            return jsonify({"error": "not found"}), 404
        return jsonify(row), 200
    finally:
        cur.close(); conn.close()



# @app.route("/api/areas/total", methods=["GET"])
# def get_total_area():
#     conn = get_db_connection()   # however you get your psycopg2 connection
#     cursor = conn.cursor()

#     try:
#         cursor.execute("""
#             SELECT 
#                 COALESCE((SELECT SUM(area) FROM greenifications), 0) AS greenifications_area,
#                 COALESCE((SELECT SUM(area) FROM greenwalls), 0) AS greenwalls_area,
#                 COALESCE((SELECT SUM(area) FROM purification_zones), 0) AS purification_zones_area
#         """)
#         row = cursor.fetchone()

#         greenifications_area, greenwalls_area, purification_zones_area = row
#         total_area = greenifications_area + greenwalls_area + purification_zones_area

#         return jsonify({
#             "greenifications_area": float(greenifications_area),
#             "greenwalls_area": float(greenwalls_area),
#             "purification_zones_area": float(purification_zones_area),
#             "total_area": float(total_area)
#         })

#     finally:
#         cursor.close()
#         conn.close()

# 健康檢查
@app.get("/healthz")
def healthz():
    return jsonify(status="ok")

if __name__ == "__main__":
    db_reset()
    print("✅ Database reset")
    db_init()
    print("✅ Database initialized with admin account")
    # print(app.url_map)
    app.run(debug=True, host="0.0.0.0", port=4080)
