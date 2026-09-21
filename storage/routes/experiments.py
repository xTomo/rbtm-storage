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

# Должно совпадать с rbtm-drivers-next/experiment/constants.py:7 — это текст
# сообщения, которым drivers сигнализируют об успешном (а не аварийном или
# принудительном) завершении эксперимента.
SUCCESSFUL_STOP_MSG = 'Experiment was finished successfully'


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

    # drivers добавляют detector_model/pixel_size в top-level документ эксперимента
    detector_info = {
        'model': insert_query.get('detector_model', ''),
        'pixel_size': insert_query.get('pixel_size', 4.25e-3),
    }

    # Все новые эксперименты создаются в формате v2
    if fs.create_experiment(experiment_id, dumps(insert_query), use_v2=True, detector_info=detector_info):
        insert_query['finished'] = False
        experiments.insert_one(insert_query)

        logger.info(f'Created experiment {experiment_id} in HDF5 v2 format')
        return jsonify({'result': 'success'})
    else:
        return jsonify({'result': 'experiment {} already exists in file system'.format(experiment_id)})


@bp_experiments.route('/finish', methods=['POST'])
def finish_experiment():
    """
    Завершает эксперимент — при любом сообщении о завершении (успех, ручная
    остановка, ошибка), не только при успехе.

    Для формата v2 финализирует HDF5 (создаёт mapping) при ЛЮБОМ таком
    сообщении: mapping (dark/empty/data/data_check indices, checkpoint-пары)
    нужен reader'у (rbtm-recon) и для прерванных/аварийно завершённых
    экспериментов — не только для успешно закончившихся.

    'finished': True выставляется только при успешном завершении; для
    неуспешного — 'stopped_with_error' с текстом причины.
    """
    if not request.data:
        logger.error('Incorrect format')
        abort(400)

    logger.info(b'Request body: ' + request.data)

    json_msg = json.loads(request.data.decode())

    experiment_id = json_msg['exp_id']

    if json_msg.get('type') == 'message':
        message = json_msg.get('message', '')
        is_success = (message == SUCCESSFUL_STOP_MSG)

        if is_success:
            update_fields = {'finished': True}
        else:
            error_text = json_msg.get('exception message', '') or json_msg.get('error', '') or message
            logger.warning(f'Experiment {experiment_id} finished with error: {error_text}')
            update_fields = {'stopped_with_error': error_text}

        db = get_db()
        result = db.experiments.update_one({'_id': experiment_id}, {'$set': update_fields})
        if result.matched_count == 0:
            logger.error(f'Experiment {experiment_id} not found')
            return jsonify({'error': f'experiment {experiment_id} not found'}), 404

        # Финализируем HDF5 v2 (mapping) при любом сообщении о завершении —
        # нужно и для прерванных экспериментов (reader читает mapping).
        from ..hdf5_v2 import finalize_experiment_v2
        hdf5_path = os.path.join('data', 'experiments', str(experiment_id), 'before_processing', f'{experiment_id}.h5')
        if os.path.exists(hdf5_path):
            try:
                finalize_experiment_v2(hdf5_path)
                logger.info(f'Finalized HDF5 v2 for experiment {experiment_id}')
            except Exception as e:
                logger.error(f'Failed to finalize HDF5 v2 for {experiment_id}: {e}')
                return jsonify({'error': f'failed to finalize HDF5 v2: {e}'}), 500

    return jsonify({'result': 'success'})


@bp_experiments.route('/<experiment_id>', methods=['DELETE'])
def delete_experiment(experiment_id):
    logger.info('Deleting experiment: ' + experiment_id)

    db = get_db()
    experiments = db['experiments']
    frames = db['frames']

    exp_query = {'_id': experiment_id}
    if experiments.count_documents(exp_query) == 0:
        logger.error('Experiment not found')
        return jsonify({'deleted': 'not found'}), 404

    json_result = jsonify({'deleted': 'success'})

    experiments.delete_many(exp_query)
    if experiments.count_documents(exp_query) != 0:
        logger.error("Can't remove experiment")
        json_result = jsonify({'deleted': 'fail'})
    else:
        logger.info("database: deleted experiment {} successfully".format(experiment_id))

    frames_query = {'exp_id': experiment_id}
    frames.delete_many(frames_query)
    if frames.count_documents(frames_query) != 0:
        logger.error("Can't remove frames")
        json_result = jsonify({'deleted': 'fail'})
    else:
        logger.info("database: deleted frames of {} successfully".format(experiment_id))

    if not fs.delete_experiment(experiment_id):
        logger.error("Can't remove experiment files from filesystem")
        json_result = jsonify({'deleted': 'fail'})

    return json_result
