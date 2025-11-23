# from flask import Flask, jsonify
# from flask_sse import sse
# import logging
# from flask_cors import CORS
# import os

# app = Flask(__name__)
# CORS(app)
# app.config["REDIS_URL"] = os.environ.get("REDIS_URL", "redis://localhost:6379")
# app.register_blueprint(sse, url_prefix='/events')

# class SSE:
#     log = logging.getLogger('apscheduler.executors.default')
#     log.setLevel(logging.INFO)
#     fmt = logging.Formatter('%(levelname)s:%(name)s:%(message)s')
#     h = logging.StreamHandler()
#     h.setFormatter(fmt)
#     log.addHandler(h)

#     @staticmethod
#     def server_sent_event(message, app_context):
#         """ Function to publish server side event """
#         with app_context():
#             sse.publish(message, type='dataUpdate')

# @app.route('/')
# def index():
#     return jsonify(["hello", "world"])

# if __name__ == '__main__':
#     app.run(debug=True)
