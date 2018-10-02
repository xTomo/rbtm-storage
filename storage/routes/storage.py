import os, json

from flask import current_app as app
from flask import Blueprint, request, abort, jsonify, Response, send_file, g

import numpy as np
import pymongo as pm

from bson.json_util import dumps
from bson.objectid import ObjectId

from . import pyframes


logger = app.logger
db = g.db
bp_storage = Blueprint('storage', __name__, url_prefix='/storage')


@bp_storage.route('/frames/post', methods=['POST'])
def new_frame():
    if not (request.files and request.form):
        logger.error('Incorrect format')
        abort(400)

    logger.info('Request body: ' + str(request.form))

    json_frame = json.loads(request.form['data'])
    experiment_id = json_frame['exp_id']

    frame = request.files['file']

    logger.info('Going to np.load...')
    image_array = np.load(frame.stream)['frame_data']
    logger.info('Image array has been loaded!')

    frame_id = db['frames'].insert(json_frame)
    frame_number = str(json_frame['frame']['number'])
    frame_type = str(json_frame['frame']['mode'])
    frame_info = dumps(db['frames'].find({"_id": ObjectId(frame_id)}))

    pyframes.add_frame(image_array, frame_info, frame_number, frame_type, frame_id, experiment_id)

    logger.info('experiment id: {} frame id: {}'.format(str(experiment_id), str(frame_id)))

    return jsonify({'result': 'success'})


@bp_storage.route('/frames_info/get', methods=['POST'])
def get_frame_info():
    if not request.data:
        logger.error('Incorrect format')
        abort(400)

    logger.info(b'Request body: ' + request.data)

    find_query = json.loads(request.data.decode())

    frames = db['frames']

    cursor = frames.find(find_query).sort('frame.number', pm.ASCENDING)

    resp = Response(response=dumps(cursor),
                    status=200,
                    mimetype="application/json")

    return resp


@bp_storage.route('/png/get', methods=['POST'])
def get_png():
    if not request.data:
        logger.error('Incorrect format')
        abort(400)

    logger.info(b'Request body: ' + request.data)

    find_query = json.loads(request.data.decode())
    frame_id = find_query['frame_id']
    experiment_id = find_query['exp_id']

    png_file_path = os.path.abspath(os.path.join('data', 'experiments', str(experiment_id), 'before_processing', 'png',
                                 str(frame_id) + '.png'))

    return send_file(png_file_path, mimetype='image/png')
