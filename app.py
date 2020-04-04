import enum
import os
import json

import requests

from celery import Celery
from flask import Flask, request, render_template, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Enum
from werkzeug.utils import redirect
from datetime import datetime
from flask_wtf import FlaskForm
from wtforms import StringField
from wtforms.validators import DataRequired


class SearchingForm(FlaskForm):
    address = StringField('address', validators=[DataRequired()])


app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql+psycopg2://postgres:aezakmi@db/postgres'
app.config['SECRET_KEY'] = 'you-will-never-guess'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

port = int(os.environ.get('PORT', 5000))

celery = Celery(app.name, broker='redis://e8-redis', backend='redis://e8-redis')
db = SQLAlchemy(app)


class Results(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    address = db.Column(db.String(300), unique=False, nullable=True)
    words_count = db.Column(db.Integer, unique=False, nullable=True)
    http_status_code = db.Column(db.Integer)


class TaskStatus(enum.Enum):
    NOT_STARTED = 1
    PENDING = 2
    FINISHED = 3


class Tasks(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    address = db.Column(db.String(300), unique=False, nullable=True)
    timestamp = db.Column(db.DateTime())
    task_status = db.Column(Enum(TaskStatus))
    http_status = db.Column(db.Integer)




class NSQD:
    def __init__(self, server):
        self.server = "http://{server}/pub".format(server=server)

    def send(self, topic, msg):
        res = requests.post(self.server, params={"topic": topic}, data=msg)
        if res.ok:
            return res


nsqd = NSQD('nsqd:4151')


@celery.task
def make_url(id):
    task = Tasks.query.get(id)
    task.task_status = 'PENDING'
    db.session.commit()
    address = task.address
    if not (address.startswith('http') or address.startswith('https')):
        address = 'http://' + address
    nsqd.send('whyr', json.dumps({"address": address, "id": str(id)}))


@celery.task
def search_words(id, address):
    python_counter = 0
    try:
        res = requests.get(address, timeout=10)
        status = res.status_code
        if res.ok:
            words = res.text.lower().split()
            python_counter = words.count('python')
    except requests.RequestException:
        status = 400
    result = Results(address=address, words_count=python_counter,
                     http_status_code=status)
    task = Tasks.query.get(id)
    task.task_status = 'FINISHED'
    db.session.add(result)
    db.session.commit()


@app.route('/', methods=['POST', 'GET'])
def search():
    searching_form = SearchingForm()
    if request.method == 'POST':
        if searching_form.validate_on_submit():
            address = request.form.get('address')
            task = Tasks(address=address, timestamp=datetime.now(),
                         task_status='NOT_STARTED')
            db.session.add(task)
            db.session.commit()
            make_url.delay(task.id)
            return redirect(url_for('results'))
        error = 'Форма не прошла валидацию.'
        return render_template('error.html', form=searching_form, error=error)
    return render_template('search.html', form=searching_form)


@app.route('/results')
def results():
    results = Results.query.all()
    return render_template('results.html', results=results)


if __name__ == '__main__':
    db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)
