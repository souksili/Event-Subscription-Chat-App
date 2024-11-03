from flask import Flask, request, jsonify, render_template, redirect, url_for, make_response
from flask_socketio import SocketIO, emit, join_room
from flask_sqlalchemy import SQLAlchemy
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
import os
from datetime import datetime
import random
import string
import qrcode

# Initialisation de Flask et SQLAlchemy
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
socketio = SocketIO(app)

# Table d'association entre abonnés et événements
event_subscriber = db.Table('event_subscriber',
    db.Column('event_id', db.Integer, db.ForeignKey('event.id'), primary_key=True),
    db.Column('subscriber_id', db.Integer, db.ForeignKey('subscriber.id'), primary_key=True)
)

# Modèles
class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    subscribers = db.relationship('Subscriber', secondary=event_subscriber, backref=db.backref('events', lazy='dynamic'))
    messages = db.relationship('Message', backref='event', lazy=True)

class Subscriber(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False)
    confirmed = db.Column(db.Boolean, default=False)
    access_code = db.Column(db.String(6), unique=True, nullable=True)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)

# Génération de code unique pour l'accès
def generate_access_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

# Route principale
@app.route('/')
def index():
    events = Event.query.all()
    return render_template('index.html', events=events)

# Validation d'email
def is_valid_email(email):
    email_regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
    return re.match(email_regex, email) is not None

# Route pour s'abonner à un événement
@app.route('/subscribe', methods=['POST'])
def subscribe():
    email = request.json.get('email')
    event_id = request.json.get('event_id')

    if not email or not is_valid_email(email):
        return jsonify({'error': 'Email invalide'}), 400

    subscriber = Subscriber.query.filter_by(email=email).first()
    if not subscriber:
        subscriber = Subscriber(email=email, access_code=generate_access_code())
        db.session.add(subscriber)

    if event_id in [event.id for event in subscriber.events]:
        return jsonify({'error': 'Déjà inscrit à cet événement'}), 400

    event = Event.query.get(event_id)
    subscriber.events.append(event)
    db.session.commit()

    # Passer l'ID de l'événement à la fonction d'envoi d'email
    send_confirmation_email(subscriber, event_id)
    return jsonify({'message': 'Inscription réussie! Veuillez confirmer votre email.'}), 200

def send_confirmation_email(subscriber, event_id):
    try:
        # Informations SMTP récupérées depuis les variables d'environnement
        smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
        smtp_port = int(os.getenv('SMTP_PORT', 587))
        smtp_username = os.getenv('SMTP_USERNAME')
        smtp_password = os.getenv('SMTP_PASSWORD')

        # Utilisation de request.host_url pour obtenir l'URL de base automatiquement
        base_url = request.host_url.rstrip('/')  # Enlever le '/' final
        confirmation_link = f"{base_url}/confirm/{subscriber.id}/{event_id}?access_code={subscriber.access_code}"

        message_body = (
            "Cher abonné,\n\n"
            "Merci de vous être inscrit à notre événement !\n"
            "Pour confirmer votre abonnement, veuillez cliquer sur le lien suivant :\n"
            f"{confirmation_link}\n\n"
            "Le QR code ci-joint vous donnera accès à la salle d'échange entre invités en temps réel.\n\n"
            "Nous sommes impatients de vous voir lors de l'événement.\n\n"
            "Cordialement,\n"
            "L'équipe d'événements"
        )

        # Génération et sauvegarde du QR code
        qr = qrcode.make(confirmation_link)
        qr_code_path = 'qr_code.png'
        qr.save(qr_code_path)

        # Création du message email
        msg = MIMEMultipart()
        msg['From'] = smtp_username
        msg['To'] = subscriber.email
        msg['Subject'] = 'Confirmation de votre abonnement'
        msg.attach(MIMEText(message_body, 'plain'))

        # Attacher le QR code à l'email
        with open(qr_code_path, "rb") as image_file:
            img = MIMEImage(image_file.read())
            img.add_header('Content-Disposition', 'attachment', filename="qr_code.png")
            msg.attach(img)

        # Envoi de l'email via SMTP
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.sendmail(smtp_username, subscriber.email, msg.as_string())

        # Supprimer le QR code après l'envoi
        os.remove(qr_code_path)

    except smtplib.SMTPException as smtp_error:
        print(f'Erreur d\'envoi de l\'email : {smtp_error}')
    except Exception as e:
        print(f'Une erreur est survenue : {e}')

# Route de confirmation
@app.route('/confirm/<int:subscriber_id>/<int:event_id>', methods=['GET'])
def confirm(subscriber_id, event_id):
    access_code = request.args.get('access_code')
    subscriber = Subscriber.query.get(subscriber_id)

    if subscriber and subscriber.access_code == access_code:
        subscriber.confirmed = True
        db.session.commit()

        # Créer une réponse pour définir le cookie
        response = make_response(redirect(url_for('chat', event_id=event_id, access_code=access_code)))
        
        # Définir le cookie avec une durée de vie d'une semaine
        response.set_cookie('access_code', access_code, max_age=7*24*60*60)  # 7 jours
        
        return response
    
    return 'Lien de confirmation invalide ou déjà confirmé.', 404

@app.route('/chat/<int:event_id>', methods=['GET'])
def chat(event_id):
    # Récupérer le code d'accès à partir de l'URL et des cookies
    access_code = request.args.get('access_code') or request.cookies.get('access_code')
    event = Event.query.get(event_id)
    
    subscriber = Subscriber.query.filter(
        Subscriber.events.any(id=event_id),
        Subscriber.access_code == access_code,
        Subscriber.confirmed == True
    ).first()

    if not event or not subscriber:
        return 'Accès refusé. Code d\'accès invalide ou abonnement non confirmé.', 403

    messages = Message.query.filter_by(event_id=event_id).all()
    return render_template('chat.html', event_id=event.id, messages=messages)

@socketio.on('join')
def on_join(data):
    event_id = data['event_id']
    join_room(event_id)

@socketio.on('send_message')
def handle_send_message(data):
    event_id = data['event_id']
    message_content = data['message']
    access_code = data.get('access_code')

    subscriber = Subscriber.query.filter(
        Subscriber.events.any(id=event_id),
        Subscriber.access_code == access_code,
        Subscriber.confirmed == True
    ).first()

    if not subscriber:
        emit('receive_message', {'message': 'Accès refusé'}, room=request.sid)
        return

    message = Message(event_id=event_id, content=message_content)
    db.session.add(message)
    db.session.commit()
    
    emit('receive_message', {'message': message_content}, room=event_id)

def populate_events():
    if Event.query.count() == 0:
        event1 = Event(title='Concert de jazz', description='Un concert de jazz en plein air.')
        event2 = Event(title='Exposition d’art', description='Exposition d’art contemporain.')
        event3 = Event(title='Conférence tech', description='Conférence sur les nouvelles technologies.')

        db.session.add_all([event1, event2, event3])
        db.session.commit()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        populate_events()
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=True)