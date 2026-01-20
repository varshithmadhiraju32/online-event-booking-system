from flask import Flask, render_template, request, redirect, session
import sqlite3
from datetime import datetime

app = Flask(__name__)
app.secret_key = "cinebook_secret"

# ================= DATABASE =================
import sqlite3

def get_db():
    con = sqlite3.connect(
        "new_database.db",
        timeout=30,
        check_same_thread=False
    )
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    return con    
# ================= AUTH =================
@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        con = get_db()
        cur = con.cursor()
        cur.execute(
            "SELECT id, name, role FROM users WHERE email=? AND password=?",
            (request.form["email"], request.form["password"])
        )
        user = cur.fetchone()
        con.close()

        if user:
            session["user_id"] = user[0]
            session["name"] = user[1]
            session["role"] = user[2]

            if user[2] == "admin":
                return redirect("/admin/events")
            elif user[2] == "organizer":
                return redirect("/organizer/events")
            else:
                return redirect("/home")

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        con = None
        try:
            con = get_db()
            cur = con.cursor()

            cur.execute("""
                INSERT INTO users (name, email, password, role)
                VALUES (?, ?, ?, ?)
            """, (
                request.form["name"],
                request.form["email"],
                request.form["password"],
                "user"
            ))

            con.commit()
            return redirect("/login")

        except sqlite3.OperationalError as e:
            return f"Database error: {e}"

        finally:
            if con:
                con.close()

    return render_template("register.html")
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# ================= USER HOME =================
@app.route("/home")
def home():
    if "user_id" not in session:
        return redirect("/login")

    con = get_db()
    cur = con.cursor()
    cur.execute("""
        SELECT 
            id, title, date, location,
            MIN(vip_price, vvip_price, mip_price, celebrity_price)
        FROM events
        GROUP BY id
    """)
    rows = cur.fetchall()
    con.close()

    events = [{
        "id": r[0],
        "title": r[1],
        "date": r[2],
        "location": r[3],
        "starting_price": r[4]
    } for r in rows]

    return render_template("home.html", events=events, role=session["role"])

# ================= EVENT DETAIL (WITH REMAINING SEATS) =================
@app.route("/event/<int:event_id>")
def event_detail(event_id):
    con = get_db()
    cur = con.cursor()

    cur.execute("""
        SELECT 
            e.id, e.title, e.description, e.date, e.location,
            e.vip_price, e.vvip_price, e.mip_price, e.celebrity_price,

            e.vip_seats - IFNULL(SUM(b.vip_qty), 0),
            e.vvip_seats - IFNULL(SUM(b.vvip_qty), 0),
            e.mip_seats - IFNULL(SUM(b.mip_qty), 0),
            e.celebrity_seats - IFNULL(SUM(b.celebrity_qty), 0)

        FROM events e
        LEFT JOIN bookings b ON e.id = b.event_id
        WHERE e.id = ?
        GROUP BY e.id
    """, (event_id,))

    r = cur.fetchone()
    con.close()

    if not r:
        return "Event not found"

    event = {
        "id": r[0],
        "title": r[1],
        "description": r[2],
        "date": r[3],
        "location": r[4],

        "vip_price": r[5],
        "vvip_price": r[6],
        "mip_price": r[7],
        "celebrity_price": r[8],

        "vip_seats": max(0, r[9]),
        "vvip_seats": max(0, r[10]),
        "mip_seats": max(0, r[11]),
        "celebrity_seats": max(0, r[12])
    }

    return render_template("event_detail.html", event=event)

# ================= BOOK EVENT (VALIDATED) =================
@app.route("/book/<int:event_id>", methods=["POST"])
def book_event(event_id):
    if "user_id" not in session:
        return redirect("/login")

    vip = int(request.form.get("vip", 0))
    vvip = int(request.form.get("vvip", 0))
    mip = int(request.form.get("mip", 0))
    celebrity = int(request.form.get("celebrity", 0))

    # Ensure at least one ticket is selected
    if (vip + vvip + mip + celebrity) < 1:
        return "❌ Please select at least one ticket"

    con = get_db()
    cur = con.cursor()

    cur.execute("""
        SELECT 
            vip_seats - IFNULL(SUM(b.vip_qty),0),
            vvip_seats - IFNULL(SUM(b.vvip_qty),0),
            mip_seats - IFNULL(SUM(b.mip_qty),0),
            celebrity_seats - IFNULL(SUM(b.celebrity_qty),0)
        FROM events e
        LEFT JOIN bookings b ON e.id = b.event_id
        WHERE e.id = ?
        GROUP BY e.id
    """, (event_id,))

    seats = cur.fetchone()

    if not seats or vip > seats[0] or vvip > seats[1] or mip > seats[2] or celebrity > seats[3]:
        con.close()
        return "❌ Not enough seats available"

    total_price = vip*300 + vvip*500 + mip*700 + celebrity*1000
    ticket_id = f"TKT{event_id}{session['user_id']}{int(datetime.now().timestamp())}"

    cur.execute("""
        INSERT INTO bookings
        (user_id,event_id,vip_qty,vvip_qty,mip_qty,celebrity_qty,
         total_price,ticket_id,booking_date)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (
        session["user_id"], event_id,
        vip, vvip, mip, celebrity,
        total_price, ticket_id, datetime.now()
    ))

    con.commit()
    # Fetch event info (title, date, location) to show on success page
    cur.execute("SELECT title, date, location FROM events WHERE id=?", (event_id,))
    ev = cur.fetchone()
    event_title = ev[0] if ev else ""
    event_date = ev[1] if ev and len(ev) > 1 else ""
    event_location = ev[2] if ev and len(ev) > 2 else ""

    con.close()

    return render_template(
        "booking_success.html",
        ticket_id=ticket_id,
        total_price=total_price,
        event_title=event_title,
        event_date=event_date,
        event_location=event_location
    )

# ================= MY BOOKINGS =================
@app.route("/my-bookings")
def my_bookings():
    if "user_id" not in session:
        return redirect("/login")

    con = get_db()
    cur = con.cursor()
    cur.execute("""
        SELECT 
            b.ticket_id,
            e.title,
            e.location,
            e.date,
            b.vip_qty,
            b.vvip_qty,
            b.mip_qty,
            b.celebrity_qty,
            b.total_price,
            b.booking_date
        FROM bookings b
        JOIN events e ON b.event_id = e.id
        WHERE b.user_id=?
        ORDER BY b.booking_date DESC
    """, (session["user_id"],))
    rows = cur.fetchall()
    con.close()

    # Default placeholder image used across the app
    placeholder_image = "https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4"

    bookings = []
    for r in rows:
        bookings.append({
            "ticket_id": r[0],
            "event_title": r[1],
            "event_location": r[2],
            "event_date": r[3],
            "vip_qty": r[4],
            "vvip_qty": r[5],
            "mip_qty": r[6],
            "celebrity_qty": r[7],
            "total_price": r[8],
            "booking_date": r[9],
            "event_image": placeholder_image
        })

    return render_template("my_bookings.html", bookings=bookings, role=session.get("role"))

@app.route("/cancel-booking/<ticket_id>")
def cancel_booking(ticket_id):
    if "user_id" not in session:
        return redirect("/login")

    con = get_db()
    cur = con.cursor()

    try:
        cur.execute("""
            SELECT event_id, vip_qty, vvip_qty, mip_qty, celebrity_qty
            FROM bookings
            WHERE ticket_id=? AND user_id=?
        """, (ticket_id, session["user_id"]))

        booking = cur.fetchone()
        if not booking:
            return "Invalid booking"

        event_id, vip, vvip, mip, celebrity = booking

        # Restore seats
        cur.execute("""
            UPDATE events
            SET vip_seats = vip_seats + ?,
                vvip_seats = vvip_seats + ?,
                mip_seats = mip_seats + ?,
                celebrity_seats = celebrity_seats + ?
            WHERE id = ?
        """, (vip, vvip, mip, celebrity, event_id))

        # Delete booking
        cur.execute("DELETE FROM bookings WHERE ticket_id=?", (ticket_id,))

        con.commit()

    except sqlite3.OperationalError as e:
        con.rollback()
        return f"Database error: {e}"

    finally:
        con.close()

    return redirect("/my-bookings")

# ================= ADMIN =================
@app.route("/admin/events")
def admin_events():
    if session.get("role") != "admin":
        return redirect("/home")

    con = get_db()
    cur = con.cursor()
    cur.execute("""
        SELECT 
            e.id,
            e.title,
            e.date,
            e.location,
            COALESCE(u.name,'Admin')
        FROM events e
        LEFT JOIN users u ON e.organizer_id = u.id
    """)
    events = cur.fetchall()
    con.close()

    return render_template("admin_events.html", events=events)


@app.route("/admin/events/delete/<int:event_id>")
def admin_delete_event(event_id):
    if session.get("role") != "admin":
        return redirect("/home")

    con = get_db()
    cur = con.cursor()
    cur.execute("DELETE FROM events WHERE id=?", (event_id,))
    con.commit()
    con.close()

    return redirect("/admin/events")


@app.route("/admin/users")
def admin_users():
    if session.get("role") != "admin":
        return redirect("/home")

    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT id,name,email,role FROM users")
    users = cur.fetchall()
    con.close()

    return render_template("admin_users.html", users=users)

# ================= ADMIN DASHBOARD =================
@app.route("/admin/dashboard")
def admin_dashboard():
    if session.get("role") != "admin":
        return redirect("/home")

    return render_template("admin_dashboard.html")



@app.route("/admin/users/role/<int:user_id>", methods=["POST"])
def admin_change_role(user_id):
    if session.get("role") != "admin":
        return redirect("/home")

    con = get_db()
    cur = con.cursor()
    cur.execute("UPDATE users SET role=? WHERE id=?", (request.form["role"], user_id))
    con.commit()
    con.close()

    return redirect("/admin/users")


@app.route("/admin/users/delete/<int:user_id>")
def admin_delete_user(user_id):
    if session.get("role") != "admin":
        return redirect("/home")

    con = get_db()
    cur = con.cursor()
    cur.execute("DELETE FROM users WHERE id=?", (user_id,))
    con.commit()
    con.close()

    return redirect("/admin/users")

# ================= ORGANIZER =================
@app.route("/organizer/events")
def organizer_events():
    if session.get("role") != "organizer":
        return redirect("/home")

    con = get_db()
    cur = con.cursor()

    cur.execute("""
        SELECT id, title, date, location
        FROM events
        WHERE organizer_id IS NOT NULL
          AND organizer_id = ?
        ORDER BY date DESC
    """, (session["user_id"],))

    events = cur.fetchall()
    con.close()

    return render_template("organizer_events.html", events=events)


@app.route("/organizer/events/add", methods=["GET", "POST"])
def organizer_add_event():
    if session.get("role") != "organizer":
        return redirect("/home")

    if request.method == "POST":
        con = get_db()
        cur = con.cursor()
        cur.execute("""
            INSERT INTO events
            (title, description, date, location,
             vip_price, vvip_price, mip_price, celebrity_price,
             vip_seats, vvip_seats, mip_seats, celebrity_seats,
             organizer_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            request.form["title"],
            request.form["description"],
            request.form["date"],
            request.form["location"],
            request.form["vip_price"],
            request.form["vvip_price"],
            request.form["mip_price"],
            request.form["celebrity_price"],
            request.form["vip_seats"],
            request.form["vvip_seats"],
            request.form["mip_seats"],
            request.form["celebrity_seats"],
            session["user_id"]
        ))
        con.commit()
        con.close()

        return redirect("/organizer/events")

    return render_template("organizer_add_event.html")


@app.route("/organizer/events/delete/<int:event_id>")
def organizer_delete_event(event_id):
    if session.get("role") != "organizer":
        return redirect("/home")

    con = get_db()
    cur = con.cursor()
    cur.execute(
        "DELETE FROM events WHERE id=? AND organizer_id=?",
        (event_id, session["user_id"])
    )
    con.commit()
    con.close()

    return redirect("/organizer/events")

# ================= ORGANIZER EDIT EVENT =================
@app.route("/organizer/events/edit/<int:event_id>", methods=["GET", "POST"])
def organizer_edit_event(event_id):
    if session.get("role") != "organizer":
        return redirect("/home")

    con = get_db()
    cur = con.cursor()

    # GET EVENT (only organizer's own event)
    cur.execute("""
        SELECT *
        FROM events
        WHERE id=? AND organizer_id=?
    """, (event_id, session["user_id"]))

    event = cur.fetchone()

    if not event:
        con.close()
        return "Unauthorized access or event not found"

    # UPDATE EVENT
    if request.method == "POST":
        cur.execute("""
            UPDATE events
            SET title=?, description=?, date=?, location=?,
                vip_price=?, vvip_price=?, mip_price=?, celebrity_price=?,
                vip_seats=?, vvip_seats=?, mip_seats=?, celebrity_seats=?
            WHERE id=? AND organizer_id=?
        """, (
            request.form["title"],
            request.form["description"],
            request.form["date"],
            request.form["location"],
            request.form["vip_price"],
            request.form["vvip_price"],
            request.form["mip_price"],
            request.form["celebrity_price"],
            request.form["vip_seats"],
            request.form["vvip_seats"],
            request.form["mip_seats"],
            request.form["celebrity_seats"],
            event_id,
            session["user_id"]
        ))

        con.commit()
        con.close()
        return redirect("/organizer/events")

    con.close()
    return render_template("organizer_edit_event.html", event=event)



# ================= RUN =================
if __name__ == "__main__":
    app.run(debug=True, use_reloader=False, threaded=False)
#====END=====