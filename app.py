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

app = Flask(__name__)
CORS(app)

load_dotenv()
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
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute("SELECT * FROM purification_zones ORDER BY created_at DESC;")
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
        image = request.files.get('image')
        image_url = None
        if image:
            filename = secure_filename(image.filename)
            upload_folder = "static/uploads"
            os.makedirs(upload_folder, exist_ok=True)
            image_path = os.path.join(upload_folder, filename)
            image.save(image_path)
            image_url = f"/{image_path}"

        # 取得表單欄位資料
        data = request.form

        cursor.execute("""
            INSERT INTO purification_zones (
                serial, year, district, type, project_name,
                maintain_unit, area, subsidy, approved_date, gps,
                subsidy_item, co2_total, co2, tsp, so2,
                no2, co, ozone, pan, image_url
            ) VALUES (%s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s)
            RETURNING *;
        """, (
            data.get("serial"),
            data.get("year"),
            data.get("district"),
            data.get("type"),
            data.get("project_name"),
            data.get("maintain_unit"),
            data.get("area"),
            data.get("subsidy"),
            data.get("approved_date"),
            data.get("gps"),
            data.get("subsidy_item"),
            data.get("co2_total"),
            data.get("co2"),
            data.get("tsp"),
            data.get("so2"),
            data.get("no2"),
            data.get("co"),
            data.get("ozone"),
            data.get("pan"),
            image_url
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

        image = files.get('image')
        image_url = None
        if image:
            filename = secure_filename(image.filename)
            upload_folder = "static/uploads"
            os.makedirs(upload_folder, exist_ok=True)
            image_path = os.path.join(upload_folder, filename)
            image.save(image_path)
            image_url = f"/{image_path}"

        cursor.execute("""
            UPDATE purification_zones SET
                serial = %s,
                year = %s,
                district = %s,
                type = %s,
                project_name = %s,
                maintain_unit = %s,
                area = %s,
                subsidy = %s,
                approved_date = %s,
                gps = %s,
                subsidy_item = %s,
                co2_total = %s,
                co2 = %s,
                tsp = %s,
                so2 = %s,
                no2 = %s,
                co = %s,
                ozone = %s,
                pan = %s,
                image_url = %s
            WHERE id = %s
            RETURNING *;
        """, (
            form.get("serial"),
            form.get("year"),
            form.get("district"),
            form.get("type"),
            form.get("project_name"),
            form.get("maintain_unit"),
            form.get("area"),
            form.get("subsidy"),
            form.get("approved_date"),
            form.get("gps"),
            form.get("subsidy_item"),
            form.get("co2_total"),
            form.get("co2"),
            form.get("tsp"),
            form.get("so2"),
            form.get("no2"),
            form.get("co"),
            form.get("ozone"),
            form.get("pan"),
            image_url,
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
    cursor = conn.cursor()

    try:
        cursor.execute("DELETE FROM purification_zones WHERE id = %s RETURNING *;", (id,))
        deleted = cursor.fetchone()
        conn.commit()
        return jsonify({"deleted": deleted})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()
    
## ---------------------------------空氣綠牆區 區塊 -------------------------------------------##

# ✅ 取得所有空氣綠牆區
@app.get("/api/green_walls")
def get_all_greenWalls():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute("SELECT * FROM green_wall ORDER BY created_at DESC;")
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
        cursor.execute("SELECT * FROM green_wall WHERE id = %s;", (id,))
        row = cursor.fetchone()

        if row:
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
        image = request.files.get('image')
        image_url = None
        if image:
            filename = secure_filename(image.filename)
            upload_folder = "static/uploads"
            os.makedirs(upload_folder, exist_ok=True)
            image_path = os.path.join(upload_folder, filename)
            image.save(image_path)
            image_url = f"/{image_path}"

        # 取得表單欄位資料
        data = request.form

        cursor.execute("""
            INSERT INTO green_wall (
                serial, year, district, type, project_name,
                maintain_unit, area, subsidy, approved_date, gps,
                subsidy_item, co2_total, co2, tsp, so2,
                no2, co, ozone, pan, image_url
            ) VALUES (%s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s)
            RETURNING *;
        """, (
            data.get("serial"),
            data.get("year"),
            data.get("district"),
            data.get("type"),
            data.get("project_name"),
            data.get("maintain_unit"),
            data.get("area"),
            data.get("subsidy"),
            data.get("approved_date"),
            data.get("gps"),
            data.get("subsidy_item"),
            data.get("co2_total"),
            data.get("co2"),
            data.get("tsp"),
            data.get("so2"),
            data.get("no2"),
            data.get("co"),
            data.get("ozone"),
            data.get("pan"),
            image_url
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

        image = files.get('image')
        image_url = None
        if image:
            filename = secure_filename(image.filename)
            upload_folder = "static/uploads"
            os.makedirs(upload_folder, exist_ok=True)
            image_path = os.path.join(upload_folder, filename)
            image.save(image_path)
            image_url = f"/{image_path}"

        cursor.execute("""
            UPDATE green_wall SET
                serial = %s,
                year = %s,
                district = %s,
                type = %s,
                project_name = %s,
                maintain_unit = %s,
                area = %s,
                subsidy = %s,
                approved_date = %s,
                gps = %s,
                subsidy_item = %s,
                co2_total = %s,
                co2 = %s,
                tsp = %s,
                so2 = %s,
                no2 = %s,
                co = %s,
                ozone = %s,
                pan = %s,
                image_url = %s
            WHERE id = %s
            RETURNING *;
        """, (
            form.get("serial"),
            form.get("year"),
            form.get("district"),
            form.get("type"),
            form.get("project_name"),
            form.get("maintain_unit"),
            form.get("area"),
            form.get("subsidy"),
            form.get("approved_date"),
            form.get("gps"),
            form.get("subsidy_item"),
            form.get("co2_total"),
            form.get("co2"),
            form.get("tsp"),
            form.get("so2"),
            form.get("no2"),
            form.get("co"),
            form.get("ozone"),
            form.get("pan"),
            image_url,
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
    cursor = conn.cursor()

    try:
        cursor.execute("DELETE FROM green_wall WHERE id = %s RETURNING *;", (id,))
        deleted = cursor.fetchone()
        conn.commit()
        return jsonify({"deleted": deleted})
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
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute("SELECT * FROM greenification ORDER BY created_at DESC;")
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
        cursor.execute("SELECT * FROM greenification WHERE id = %s;", (id,))
        row = cursor.fetchone()

        if row:
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
        image = request.files.get('image')
        image_url = None
        if image:
            filename = secure_filename(image.filename)
            upload_folder = "static/uploads"
            os.makedirs(upload_folder, exist_ok=True)
            image_path = os.path.join(upload_folder, filename)
            image.save(image_path)
            image_url = f"/{image_path}"

        # 取得表單欄位資料
        data = request.form

        cursor.execute("""
            INSERT INTO greenification (
                serial, year, district, type, project_name,
                maintain_unit, area, subsidy, approved_date, gps,
                subsidy_item, co2_total, co2, tsp, so2,
                no2, co, ozone, pan, image_url
            ) VALUES (%s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s)
            RETURNING *;
        """, (
            data.get("serial"),
            data.get("year"),
            data.get("district"),
            data.get("type"),
            data.get("project_name"),
            data.get("maintain_unit"),
            data.get("area"),
            data.get("subsidy"),
            data.get("approved_date"),
            data.get("gps"),
            data.get("subsidy_item"),
            data.get("co2_total"),
            data.get("co2"),
            data.get("tsp"),
            data.get("so2"),
            data.get("no2"),
            data.get("co"),
            data.get("ozone"),
            data.get("pan"),
            image_url
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

        image = files.get('image')
        image_url = None
        if image:
            filename = secure_filename(image.filename)
            upload_folder = "static/uploads"
            os.makedirs(upload_folder, exist_ok=True)
            image_path = os.path.join(upload_folder, filename)
            image.save(image_path)
            image_url = f"/{image_path}"

        cursor.execute("""
            UPDATE greenification SET
                serial = %s,
                year = %s,
                district = %s,
                type = %s,
                project_name = %s,
                maintain_unit = %s,
                area = %s,
                subsidy = %s,
                approved_date = %s,
                gps = %s,
                subsidy_item = %s,
                co2_total = %s,
                co2 = %s,
                tsp = %s,
                so2 = %s,
                no2 = %s,
                co = %s,
                ozone = %s,
                pan = %s,
                image_url = %s
            WHERE id = %s
            RETURNING *;
        """, (
            form.get("serial"),
            form.get("year"),
            form.get("district"),
            form.get("type"),
            form.get("project_name"),
            form.get("maintain_unit"),
            form.get("area"),
            form.get("subsidy"),
            form.get("approved_date"),
            form.get("gps"),
            form.get("subsidy_item"),
            form.get("co2_total"),
            form.get("co2"),
            form.get("tsp"),
            form.get("so2"),
            form.get("no2"),
            form.get("co"),
            form.get("ozone"),
            form.get("pan"),
            image_url,
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
@app.delete("/api/greenifications/<int:id>")
@jwt_required
def delete_greenification(id):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("DELETE FROM greenification WHERE id = %s RETURNING *;", (id,))
        deleted = cursor.fetchone()
        conn.commit()
        return jsonify({"deleted": deleted})
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
        data = request.form
        image = request.files.get("image")
        image_url = None

        # if image:
        #     filename = secure_filename(image.filename)
        #     image_path = os.path.join(UPLOAD_FOLDER, filename)
        #     image.save(image_path)
        #     image_url = f"/{image_path}"

        cursor.execute("""
            INSERT INTO tree_intros (title, date, content, image_url)
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
        data = cursor.fetchone()
        if data:
            return jsonify(data)
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

        if image:
            filename = secure_filename(image.filename)
            image_path = os.path.join(UPLOAD_FOLDER, filename)
            image.save(image_path)
            image_url = f"/{image_path}"

        cursor.execute("""
            UPDATE tree_intros
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
            image_url,
            id
        ))

        updated = cursor.fetchone()
        conn.commit()

        if updated:
            return jsonify(updated)
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
    cursor = conn.cursor()

    try:
        cursor.execute("DELETE FROM tree_intros WHERE id = %s RETURNING id;", (id,))
        deleted = cursor.fetchone()
        conn.commit()

        if deleted:
            return jsonify({"message": "刪除成功"})
        else:
            return jsonify({"error": "ID 不存在"}), 404

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()

## ---------------------------------公告區塊  ------------------------------------------
@app.post("/api/announcement")
@jwt_required
def create_announcement():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        data = request.form
        cursor.execute("""
            INSERT INTO announcement (title, date, content)
            VALUES (%s, %s, %s)
            RETURNING *;
        """, (
            data.get("title"),
            data.get("date"),
            data.get("content")
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

@app.get("/api/announcement")
def get_announcements():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute("SELECT * FROM announcement ORDER BY id DESC;")
        data = cursor.fetchall()
        return jsonify(data)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()
@app.get("/api/announcement/<int:id>")
def get_announcement(id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute("SELECT * FROM announcement WHERE id = %s;", (id,))
        data = cursor.fetchone()
        if data:
            return jsonify(data)
        else:
            return jsonify({"error": "找不到資料"}), 404

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()
@app.put("/api/announcement/<int:id>")
def update_announcement_intro(id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        data = request.form
        

        cursor.execute("""
            UPDATE announcement
            SET title = %s,
                date = %s,
                content = %s,
            WHERE id = %s
            RETURNING *;
        """, (
            data.get("title"),
            data.get("date"),
            data.get("content"),
            id
        ))

        updated = cursor.fetchone()
        conn.commit()

        if updated:
            return jsonify(updated)
        else:
            return jsonify({"error": "ID 不存在"}), 404

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()
@app.delete("/api/announcement/<int:id>")
def delete_announcement(id):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("DELETE FROM announcement WHERE id = %s RETURNING id;", (id,))
        deleted = cursor.fetchone()
        conn.commit()

        if deleted:
            return jsonify({"message": "刪除成功"})
        else:
            return jsonify({"error": "ID 不存在"}), 404

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
        data = request.form
        cursor.execute("""
            INSERT INTO result (title, date, content)
            VALUES (%s, %s, %s)
            RETURNING *;
        """, (
            data.get("title"),
            data.get("date"),
            data.get("content")
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
        data = cursor.fetchone()
        if data:
            return jsonify(data)
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
        

        cursor.execute("""
            UPDATE result
            SET title = %s,
                date = %s,
                content = %s
            WHERE id = %s
            RETURNING *;
        """, (
            data.get("title"),
            data.get("date"),
            data.get("content"),
            id
        ))

        updated = cursor.fetchone()
        conn.commit()

        if updated:
            return jsonify(updated)
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
    cursor = conn.cursor()

    try:
        cursor.execute("DELETE FROM result WHERE id = %s RETURNING id;", (id,))
        deleted = cursor.fetchone()
        conn.commit()

        if deleted:
            return jsonify({"message": "刪除成功"})
        else:
            return jsonify({"error": "ID 不存在"}), 404

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
        data = request.form
        cursor.execute("""
            INSERT INTO files (title, date, note)
            VALUES (%s, %s, %s)
            RETURNING *;
        """, (
            data.get("title"),
            data.get("date"),
            data.get("note")
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
        data = cursor.fetchone()
        if data:
            return jsonify(data)
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
        

        cursor.execute("""
            UPDATE files
            SET title = %s,
                date = %s,
                note = %s
            WHERE id = %s
            RETURNING *;
        """, (
            data.get("title"),
            data.get("date"),
            data.get("note"),
            id
        ))

        updated = cursor.fetchone()
        conn.commit()

        if updated:
            return jsonify(updated)
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
    cursor = conn.cursor()

    try:
        cursor.execute("DELETE FROM files WHERE id = %s RETURNING id;", (id,))
        deleted = cursor.fetchone()
        conn.commit()

        if deleted:
            return jsonify({"message": "刪除成功"})
        else:
            return jsonify({"error": "ID 不存在"}), 404

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()




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
