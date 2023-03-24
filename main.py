""" Module providingFunction printing python version """
import os
import pathlib
from flask import Flask, session, render_template, request, redirect, url_for
import db
from db import Change, User
from werkzeug.utils import secure_filename
from google.oauth2 import id_token
import requests
import enc
from google.auth.transport import requests as rq
from flask_socketio import SocketIO
from threading import Lock
import json


THREAD = None
thread_lock = Lock()
# returns list of all users
active_users = db.get_users()


SCOPES = ['https://www.googleapis.com/auth/calendar',
          "https://www.googleapis.com/auth/userinfo.profile",
          "https://www.googleapis.com/auth/userinfo.email", "openid"]


# Database Code
basedir = os.path.abspath(os.path.dirname(__file__))


# App configuration
def create_app():

    app = Flask(__name__)
    app.config['UPLOAD_FOLDER'] = basedir + "/static/uploads"
    app.config['MAX_CONTENT_PATH'] = 150000
    app.config['SERVER_NAME'] = "127.0.0.1:5000"
    app.config['DEBUG'] = True
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.secret_key = os.environ.get(
        "FLASK_SECRET_KEY", default="supersecretkey")

    return app


app = create_app()
socketio = SocketIO(app, cors_allowed_origins='*')

"""
Stream messages as they come in 
"""


def get_user_messages():
    """request messages from user"""
    messages = []
    groups = session.get("groups")
    for i in groups:
        messages.append(db.loadGroupMessages(i))
    return messages


def background_thread():
    """Calls in the background updateMessages every minute"""
    while True:
        socketio.emit('updateMessages', json.dumps(
            get_user_messages(), separators=(',', ':')))

        socketio.sleep(60)


with open('keys/clientid.txt', 'rb') as p:
    c = p.read()
CLIENT_ID = enc.decrypt(c)

with open('keys/s.txt', 'rb') as p:
    s = p.read()

SECR = enc.decrypt(s)

client_secrets_file = os.path.join(
    pathlib.Path(__file__).parent, "client_secret.json")

session = {
    "start": False,
    "user": ""
}


@app.route("/")
def index():
    """routing to index html"""
    return render_template("index.html")


@socketio.on('connect')
def connect():
    """connecting client"""
    global THREAD
    print('Client connected')

    global THREAD
    with thread_lock:
        if THREAD is None:
            THREAD = socketio.start_background_task(background_thread)


@socketio.on('disconnect')
def disconnect():
    """Disconnecting socket"""
    print("disconnected")


@app.route("/google-login")
def google_login():
    """loggin in to google"""
    return redirect(f"https://accounts.google.com/o/oauth2/v2/auth?"
                    f"response_type=code&client_id={CLIENT_ID}&"
                    f"redirect_uri={url_for('google_callback', _external=True)}&"
                    f"scope=openid%20email%20profile")


@app.route("/callback")
def google_callback():
    """ calling back"""
    code = request.args.get("code")
    token_url = "https://oauth2.googleapis.com/token"
    session["start"] = True

    data = {
        "code": code,
        "client_id": CLIENT_ID,
        "client_secret": SECR,
        "redirect_uri": url_for('google_callback', _external=True),
        "grant_type": "authorization_code"
    }
    r = requests.post(token_url, data=data)
    try:
        token = r.json()["id_token"]
        claims = id_token.verify_oauth2_token(
            token,
            rq.Request(),
            CLIENT_ID
        )
        session["email"] = claims["email"]
        session["user"] = db.googleSignup(session.get("email"))
        session["type"] = 'google'
        return flask.redirect('/home')

    except KeyError:
        return redirect(url_for("/home"))


@app.route('/signUp')
def signUp():
    """routing to to signup"""
    return render_template("signUp.html")


@app.route('/signUp', methods=['POST'])
def trysignUp():
    """routing to to signup"""
    active_usernames = []
    for user in active_users:
        active_usernames.append(user["username"])
    if (request.form["name"] in active_usernames):
        return render_template("signUp.html", alarm="1")
    signup = User().signUp()
    if signup == True:
        session["user"] = signup
        return render_template("home.html")
    else:
        return render_template("signUp.html", alarm="1")


@app.route('/changeInfo', methods=['POST'])
def changeInfo():
    """Changing user info"""
    changeInfo = Change().changeInfo(session.get("user").get("_id"))
    if changeInfo == True:
        session["user"] = changeInfo
        return "info updated"
    else:
        return render_template("settings.html", alarm="1")


@app.route('/changegoogleInfo', methods=['POST'])
def changegoogleInfo():
    """Changing google account info"""
    googleAdd = Change().googlesettingsInfo(session.get("user").get("_id"))
    if googleAdd == True:
        session["user"] = googleAdd
        return "info added"
    else:
        return render_template("settings.html", alarm="1")


@app.route('/login')
def login():
    """routing to login"""
    if not session.get("user"):
        return render_template("login.html")
    return redirect('/home')

# Logs out current session


@app.route('/logout')
def logout():
    """routing to logout"""
    if not session.get("user"):
        return render_template("login.html")
    session['user'] = ""
    return redirect('/')


@app.route('/login', methods=["POST"])
def trylogin():
    """checking login info"""
    data = request.form
    user = data.get("user")
    password = data.get("password")
    login = db.login(user, password)
    if login != False:
        session['user'] = login
        if session['user']['username'] == "TestUser1":
            return logout()
        else:
            return redirect('/home')
    else:
        return render_template("login.html", alarm="1")


@app.route('/home')
def home():
    """routing to Home"""
    if not session.get("user") and not session.get("email"):
        return redirect('/')
    if not session.get("groups"):
        groups = []
    # Searches db for groups by user id
    userchats = db.userChats(session.get("user").get("_id"))
    # Need a route to send to a page without userchats for chats under 1
    if len(userchats) > 0:
        for userchat in userchats:
            groups.append(userchat["_id"])
    session["groups"] = groups
    if session.get("user").get("username"):
        return render_template("home.html", user=session.get("user").get("username"))
    if session.get("user").get("email"):
        return render_template("home.html", user=session.get("user").get("email"))


@app.route('/search')
def search():
    """routing to search"""
    return render_template("search.html")


@app.route('/search1', methods=["GET"])
def searchDB():
    """routing to searchDB"""
    query = request.args.get('query')
    key = ""
    query = query.split(": ")
    if len(query) < 2:
        results = db.existingChats(query[0], "name")
    else:
        flter = query[0].strip()
        keyword = query[1]
        chats = []
        # searches DB by username
        if flter == "user":
            results, profiles = db.searchUsers(keyword, "username")
            key = "user"
        # searches DB by group name
        elif flter == "group":
            results = db.existingChats(keyword, "name")
            key = "group"
        # searches DB by group description
        elif flter == "gdesc":
            results = db.existingChats(keyword, "description")
            key = "group"
        # search DB by user messages coming soon
    if results != "No results found...":
        if key == "user":
            res = {
                "results": results,
                "profiles": profiles
            }
            return render_template("results.html", groups=[], results=res, key=key)
        else:
            return render_template("results.html",
                                   results=results, groups=session.get("groups"), key=key)
    else:
        return render_template("results.html", groups=[], results=[], key=key)


@app.route('/settings')
def setting():
    """routing to SETTINGS"""
    if not session.get("type"):
     # To regular settings
        return render_template('settings.html')
    else:
        return render_template('googleSettings.html')


@app.route('/quiz')
def quiz():
    """routing to quiz"""
    if not session.get("user"):
        return redirect('/')
    mm = db.loadQuizAnswers(session.get("user").get("_id"))
    print(mm)
    return render_template("quiz.html", mm=mm)


@app.route('/savequiz', methods=["POST"])
def savequiz():
    """routing to saved quiz after receiving them"""
    data = request.form
    db.savequiz(data, session.get("user").get("_id"))
    return redirect('quiz')


@app.route('/createGroup', methods=["GET", "POST"])
def createGroup():
    """routing to createGroup"""

    if not session.get("user"):
        return redirect('/')
    if request.method == "POST":
        userid = session.get("user").get("_id")
        photo = request.files['groupPhoto']
        upload(photo)
        db.createChat(request, photo, userid)
        return redirect('/existingGroups')
    return render_template("createGroup.html")


def upload(file):
    """routing to file uploaded"""
    file.save(os.path.join(
        app.config['UPLOAD_FOLDER'], secure_filename(file.filename)))


@app.route('/existingGroups', methods=["GET", "POST"])
def currentGroups():
    """routing to currentGroups"""
    if not session.get("user"):
        return redirect('/')
    messages = []
    groups = []
    # Searches db for groups by user id
    userchats = db.userChats(session.get("user").get("_id"))
    # Need a route to send to a page without userchats for chats under 1
    if len(userchats) > 0:
        for userchat in userchats:
            groups.append(userchat["_id"])
            messages.append(db.loadGroupMessages(userchat["_id"]))
        session["groups"] = groups
        return render_template("existingGroups.html",
                               user=session.get("user"),
                               len=len(userchats),
                               results=userchats, messages=messages)
    else:
        # Temporary, sending to create group or would it be better to send to search page???
        return redirect("/createGroup")


@socketio.on('savemessage')
def saveUserMessage(json):
    """saves user messages to the database"""
    print('received message: ' + str(json))
    db.saveMessage(json, session.get("user").get("_id"))


@app.route('/profile', methods=["GET", "POST"])
def userProfile():
    """routing to userProfile"""
    if not session.get("user"):
        return redirect('/')
    if request.method == "POST":
        photo = request.files['profilepic']
        print(photo.filename)
        if photo.filename == "" or None:
            print("No photo added")
        else:
            # uploads a photo if given
            upload(photo)
        db.saveUserProfile(session.get("user").get("_id"), request)
    profile = db.userProfile(session.get("user").get("_id"))
    return render_template("profile.html", profile=profile)


@app.route('/join', methods=["POST"])
def joingroup():
    if request.method == "POST":
        value = request.form['join']
        db.joingroup(value, session.get("user").get("_id"))
        return redirect('/existingGroups')


# created a reloader for easier code running in localhost
# debug to find bugs
if __name__ == '__main__':
    # Added websocket functionality to stream data while running.
    socketio.run(app)
