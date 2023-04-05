""" Module providingFunction printing python version """
import os
import pathlib
from threading import Lock
import json
from flask import Flask, session, render_template, request, redirect, url_for
from flask_caching import Cache
from google.auth.transport import requests as rq
from google.oauth2 import id_token
from datetime import datetime, timedelta
import requests
from flask_socketio import SocketIO
from werkzeug.utils import secure_filename
import db
from db import Change, User
import enc



THREAD = None
thread_lock = Lock()
# returns list of all users
active_users = db.get_users()
active_google_users= db.get_google()

SCOPES = ['https://www.googleapis.com/auth/calendar',
          "https://www.googleapis.com/auth/userinfo.profile",
          "https://www.googleapis.com/auth/userinfo.email", "openid"]


# Database Code
basedir = os.path.abspath(os.path.dirname(__file__))


# App configuration
def create_app():
    """creates initial application"""
    app = Flask(__name__)
    app.config['UPLOAD_FOLDER'] = basedir + "/static/uploads"
    app.config['MAX_CONTENT_PATH'] = 150000
    app.config['SERVER_NAME'] = "127.0.0.1:5000"
    app.config['DEBUG'] = True
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.secret_key = os.environ.get(
        "FLASK_SECRET_KEY", default="supersecretkey")
    app.config['CACHE_TYPE'] = "SimpleCache"
    app.config['CACHE_DEFAULT_TIMEOUT'] = 300
    return app


app_init = create_app()
cache= Cache(app_init)
socketio = SocketIO(app_init, cors_allowed_origins='*')

"""
Stream messages as they come in 
"""


def get_user_messages():
    """request messages from user"""
    time= datetime.strptime(session.get("time"),'%Y-%m-%d %H:%M:%S')
    messages = []
    groups = session.get("groups")
    for i in groups:
        messages.append(db.messages_by_time(time.timestamp(),i))
    return messages


def background_thread():
    """Calls in the background updateMessages every 60 seconds"""
    while True:
        print("Running get_user_messages")
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
    "user": "",
    "time": str(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
}


@app_init.route("/")
def index():
    """routing to index html"""
    return render_template("index.html")


@socketio.on('connect')
def connect():
    """connecting client"""
    global THREAD
    print('Client connected')
    socketio.start_background_task(background_thread)

    # global THREAD
    # with thread_lock:
        # if THREAD is None:
            # print('Starting background task')
            # THREAD = socketio.start_background_task(background_thread)


@socketio.on('disconnect')
def disconnect():
    """Disconnecting socket"""
    print("disconnected")


@socketio.on('updateTime')
def update_local_time(time):
    """updates time"""
    print('received time: ' + str(time))
    session["local"]= time
    
@app_init.route("/google-login")
def google_login():
    """loggin in to google"""
    return redirect(f"https://accounts.google.com/o/oauth2/v2/auth?"
                    f"response_type=code&client_id={CLIENT_ID}&"
                    f"redirect_uri={url_for('google_callback', _external=True)}&"
                    f"scope=openid%20email%20profile")


@app_init.route("/callback")
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
    res = requests.post(token_url, data=data)
    try:
        token = res.json()["id_token"]
        claims = id_token.verify_oauth2_token(
            token,
            rq.Request(),
            CLIENT_ID
        )
        session["email"] = claims["email"]
        session["user"] = db.googlesignup(session.get("email"))
        session["type"] = 'google'
        return redirect('/home')

    except KeyError:
        return redirect(url_for("/home"))


@app_init.route('/signUp')
def signup():
    """routing to to signup"""
    return render_template("signUp.html")


@app_init.route('/signUp', methods=['POST'])
def trysignup():
    """routing to to signup"""
    active_usernames = []
    for user in active_users:
        active_usernames.append(user["username"])
    if request.form["name"] in active_usernames:
        return render_template("signUp.html", alarm="1")
    sign_up, new_user = User().signup()
    if sign_up is True:
        session["user"] = new_user
        return render_template("home.html")
    return render_template("signUp.html", alarm="1")


@app_init.route('/changeInfo', methods=['POST'])
def changeinfo():
    """Changing user info"""
    change_info = Change().change_info(session.get("user").get("_id"))
    if change_info is True:
        session["user"] = change_info
        return "info updated"
    return render_template("settings.html", alarm="1")


@app_init.route('/changegoogleInfo', methods=['POST'])
def changegoogleinfo():
    """Changing google account info"""
    google_add = Change().googlesettingsinfo(session.get("user").get("_id"))
    if google_add is True:
        session["user"] = google_add
        return "info added"
    return render_template("settings.html", alarm="1")


@app_init.route('/login')
def login():
    """routing to login"""
    if not session.get("user"):
        return render_template("login.html")
    return redirect('/home')

# Logs out current session


@app_init.route('/logout')
def logout():
    """routing to logout"""
    if not session.get("user"):
        return render_template("login.html")
    session['user'] = ""
    return redirect('/')


@app_init.route('/login', methods=["POST"])
def trylogin():
    """checking login info"""
    data = request.form
    user = data.get("user")
    password = data.get("password")
    login_user = db.login(user, password)
    if login_user is not False:
        session['user'] = login_user
        if session['user']['username'] == "TestUser1":
            return logout()
        return redirect('/home')
    return render_template("login.html", alarm="1")


@app_init.route('/home')
def home():
    """routing to Home"""
    groups=[]
    if not session.get("user") and not session.get("email"):
        return redirect('/')
    # Searches db for groups by user id
    userchats = db.userchats(session.get("user").get("_id"))
    # Need a route to send to a page without userchats for chats under 1
    if len(userchats) > 0:
        for userchat in userchats:
            groups.append(userchat["_id"])
    session["groups"] = groups
    if session.get("user").get("username"):
        return render_template("home.html", user=session.get("user").get("username"))
    if session.get("user").get("email"):
        return render_template("home.html", user=session.get("user").get("email"))


@app_init.route('/search')
def search():
    """routing to search"""
    return render_template("search.html")


@app_init.route('/search1', methods=["GET"])
def searchdb():
    """routing to searchDB"""
    query = request.args.get('query')
    key = ""
    query = query.split(": ")
    if len(query) < 2:
        results = db.existingchats(query[0], "name")
    else:
        flter = query[0].strip()
        keyword = query[1]
        # searches DB by username
        if flter == "user":
            results, profiles = db.searchusers(keyword, "username")
            key = "user"
        # searches DB by group name
        elif flter == "group":
            results = db.existingchats(keyword, "name")
            key = "group"
        # searches DB by group description
        elif flter == "gdesc":
            results = db.existingchats(keyword, "description")
            key = "group"
        # search DB by user messages coming soon
    if results != "No results found...":
        if key == "user":
            res = {
                "results": results,
                "profiles": profiles
            }
            return render_template("results.html", groups=[], results=res, key=key)
        return render_template("results.html",
                                   results=results, groups=session.get("groups"), key=key)
    return render_template("results.html", groups=[], results=[], key=key)


@app_init.route('/settings')
def setting():
    """routing to SETTINGS"""
    if not session.get("type"):
     # To regular settings
        return render_template('settings.html')
    return render_template('googleSettings.html')


@app_init.route('/quiz')
def quiz():
    """routing to quiz"""
    if not session.get("user"):
        return redirect('/')
    match = db.loadquizanswers(session.get("user").get("_id"))
    return render_template("quiz.html", mm= match)


@app_init.route('/savequiz', methods=["POST"])
def savequiz():
    """routing to saved quiz after receiving them"""
    data = request.form
    db.savequiz(data, session.get("user").get("_id"))
    return redirect('quiz')


@app_init.route('/createGroup', methods=["GET", "POST"])
def creategroup():
    """routing to createGroup"""
    print(session.get("user"))
    users_list= list(active_users)
    for google_users in active_google_users:
        users_list.append(google_users)
    try:
        users_list.remove(session.get("user"))
    except:
        print("No users loaded")
        users_list= list(db.get_users())
        for google_users in db.get_google():
            users_list.append(google_users)
        users_list.remove(session.get("user"))
    users_by_username= []
    for users in users_list:
        try: 
            user= {
            "user" : users["username"],
            "email": users["email"]
        }
        except:
            user= {
            "user" : users["email"],
            "email": users["email"]
        }
       
        users_by_username.append(json.loads(json.dumps(user)))
    if not session.get("user"):
        return redirect('/')
    if request.method == "POST":
        userid = session.get("user").get("_id")
        photo = request.files['groupPhoto']
        upload(photo)
        db.createchat(request, photo, userid)
        return redirect('/loading')
    return render_template("createGroup.html", userobj= users_by_username)


def upload(file):
    """routing to file uploaded"""
    file.save(os.path.join(
        app_init.config['UPLOAD_FOLDER'], secure_filename(file.filename)))


@app_init.route('/existingGroups', methods=["GET", "POST"])
@cache.cached(timeout=50)
def current_groups():
    """routing to currentGroups"""
    if not session.get("user"):
        return redirect('/')
    messages = []
    groups = []
    # Searches db for groups by user id
    userchats = db.userchats(session.get("user").get("_id"))
    # Need a route to send to a page without userchats for chats under 1
    if len(userchats) > 0:
        for userchat in userchats:
            groups.append(userchat["_id"])
            messages.append(db.loadgroupmessages(userchat["_id"]))
        session["groups"] = groups
        session["load"] = True
        return render_template("existingGroups.html",
                               user=session.get("user"),
                               len=len(userchats),
                               results=userchats, messages=messages)
        # Temporary, sending to create group or would it be better to send to search page???
    return redirect("/createGroup")


@socketio.on('savemessage')
def save_user_message(message):
    """saves user messages to the database"""
    print('received message: ' + str(message))
    response= db.savemessage(message, session.get("user").get("_id"))
    if len(response) > 0:
        print('sending response: ' + str(message))
        socketio.emit('returnMessageResponse', json.dumps(response, separators=(',', ':')))

@app_init.route('/profile', methods=["GET", "POST"])
def user_profile():
    """routing to userProfile"""
    if not session.get("user"):
        return redirect('/')
    if request.method == "POST":
        photo = request.files['profilepic']
        print(photo.filename)
        if photo.filename == '':
            print("No photo added")
        else:
            # uploads a photo if given
            upload(photo)
        db.saveuserprofile(session.get("user").get("_id"), request)
    profile = db.userprofile(session.get("user").get("_id"))
    return render_template("profile.html", profile=profile)


@app_init.route('/join', methods=["POST"])
def joingroup():
    """routing to joingroup"""
    if request.method == "POST":
        value = request.form['join']
        db.joingroup(value, session.get("user").get("_id"))
        return redirect('/existingGroups')
        
@app_init.route('/loading')        
def loading():        
    """adds buffer for existing groups loading page"""
    return render_template("loading.html")

# created a reloader for easier code running in localhost
# debug to find bugs
if __name__ == '__main__':
    # Added websocket functionality to stream data while running.
    socketio.run(app_init)
