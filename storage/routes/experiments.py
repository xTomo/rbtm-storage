import json
import os

import pymongo as pm
from bson.json_util import dumps
from flask import current_app as app
from flask import jsonify, request, abort, Response, Blueprint

from storage import filesystem as fs
from ..db import get_db

logger = app.logger
bp_experiments = Blueprint('experiments', __name__, url_prefix='/storage/experiments')


# return experiments by request json file. return json
@bp_experiments.route('/get', methods=['POST'])
def get_experiments():
    if not request.data:
        logger.error('Incorrect format')
        abort(400)

    logger.info(b'Request body: ' + request.data)

    find_query = json.loads(request.data.decode())

    db = get_db()
    experiments = db['experiments']

    cursor = experiments.find(find_query).sort('timestamp', pm.DESCENDING)

    resp = Response(response=dumps(cursor),
                    status=200,
                    mimetype="application/json")

    return resp


# create new experiment, need json file as request return result:success json if success
@bp_experiments.route('/create', methods=['POST'])
def create_experiment():
    """
    Создаёт новый эксперимент.
    Все новые эксперименты создаются в формате HDF5 v2.
    """
    if not request.data:
        logger.error('Incorrect format')
        abort(400)

    logger.info(b'Request body: ' + request.data)

    insert_query = json.loads(request.data.decode())

    db = get_db()
    experiments = db['experiments']

    experiment_id = insert_query['exp_id']
    insert_query.pop('exp_id', None)
    insert_query['_id'] = experiment_id

    # Все новые эксперименты создаются в формате v2
    if fs.create_experiment(experiment_id, dumps(insert_query), use_v2=True):
        insert_query['finished'] = False
        experiments.insert(insert_query)

        logger.info(f'Created experiment {experiment_id} in HDF5 v2 format')
        return jsonify({'result': 'success'})
    else:
        return jsonify({'result': 'experiment {} already exists in file system'.format(experiment_id)})


@bp_experiments.route('/finish', methods=['POST'])
def finish_experiment():
    """
    Завершает эксперимент.
    Для формата v2 создаёт mapping индексы.
    """
    if not request.data:
        logger.error('Incorrect format')
        abort(400)

    logger.info(b'Request body: ' + request.data)

    json_msg = json.loads(request.data.decode())

    experiment_id = json_msg['exp_id']

    if json_msg['type'] == 'message':
        if json_msg['message'] == 'Experiment was finished successfully':
            db = get_db()
            db.experiments.update({'_id': experiment_id},
                                  {'$set': {'finished': True}})
            
            # Для v2 финализируем HDF5 (создаём mapping)
            from ..hdf5_v2 import finalize_experiment_v2
            hdf5_path = os.path.join('data', 'experiments', str(experiment_id), 'before_processing', f'{experiment_id}.h5')
            if os.path.exists(hdf5_path):
                try:
                    finalize_experiment_v2(hdf5_path)
                    logger.info(f'Finalized HDF5 v2 for experiment {experiment_id}')
                except Exception as e:
                    logger.warning(f'Failed to finalize HDF5 v2 for {experiment_id}: {e}')
        else:
            logger.warning(json_msg['exception message'] + json_msg['error'])

    return jsonify({'result': 'success'})


@bp_experiments.route('/<experiment_id>', methods=['DELETE'])
def delete_experiment(experiment_id):
    json_result = jsonify({'deleted': 'success'})
    logger.info('Deleting experiment: ' + experiment_id)

    db = get_db()
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
