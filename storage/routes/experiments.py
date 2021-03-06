import json

import pymongo as pm
from bson.json_util import dumps
from flask import current_app as app
from flask import jsonify, request, abort, Response, Blueprint, g

from storage import filesystem as fs

logger = app.logger
db = g.db
bp_experiments = Blueprint('experiments', __name__, url_prefix='/storage/experiments')


# return experiments by request json file. return json
@bp_experiments.route('/get', methods=['POST'])
def get_experiments():
    if not request.data:
        logger.error('Incorrect format')
        abort(400)

    logger.info(b'Request body: ' + request.data)

    find_query = json.loads(request.data.decode())

    experiments = db['experiments']

    cursor = experiments.find(find_query).sort('timestamp', pm.DESCENDING)

    resp = Response(response=dumps(cursor),
                    status=200,
                    mimetype="application/json")

    return resp


# create new experiment, need json file as request return result:success json if success
@bp_experiments.route('/create', methods=['POST'])
def create_experiment():
    if not request.data:
        logger.error('Incorrect format')
        abort(400)

    logger.info(b'Request body: ' + request.data)

    insert_query = json.loads(request.data.decode())

    experiments = db['experiments']

    experiment_id = insert_query['exp_id']
    insert_query.pop('exp_id', None)
    insert_query['_id'] = experiment_id

    if fs.create_experiment(experiment_id, dumps(insert_query)):
        insert_query['finished'] = False
        experiments.insert(insert_query)

        return jsonify({'result': 'success'})
    else:
        return jsonify({'result': 'experiment {} already exists in file system'.format(experiment_id)})


@bp_experiments.route('/finish', methods=['POST'])
def finish_experiment():
    if not request.data:
        logger.error('Incorrect format')
        abort(400)

    logger.info(b'Request body: ' + request.data)

    json_msg = json.loads(request.data.decode())

    experiment_id = json_msg['exp_id']

    if json_msg['type'] == 'message':
        if json_msg['message'] == 'Experiment was finished successfully':
            db.experiments.update({'_id': experiment_id},
                                  {'$set': {'finished': True}})
        else:
            logger.warning(json_msg['exception message'] + json_msg['error'])

    return jsonify({'result': 'success'})


@bp_experiments.route('/<experiment_id>', methods=['DELETE'])
def delete_experiment(experiment_id):
    json_result = jsonify({'deleted': 'success'})
    logger.info('Deleting experiment: ' + experiment_id)

    experiments = db['experiments']
    frames = db['frames']

    exp_query = {'_id': experiment_id}
    cursor = experiments.find(exp_query)
    if cursor.count() == 0:
        logger.error('Experiment not found')
    else:
        experiments.remove(exp_query)
        if cursor.count() != 0:
            logger.error("Can't remove experiment")
            json_result = jsonify({'deleted': 'fail'})
        else:
            logger.info("database: deleted experiment {} successfully".format(experiment_id))

    frames_query = {'exp_id': experiment_id}
    frames.remove(frames_query)
    if frames.find(frames_query).count() != 0:
        logger.error("Can't remove frames")
        json_result = jsonify({'deleted': 'fail'})
    else:
        logger.info("database: deleted frames of {} successfully".format(experiment_id))

    fs.delete_experiment(experiment_id)

    # db['reconstructions'].remove(request.get_json())

    return json_result
