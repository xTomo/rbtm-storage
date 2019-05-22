import os
import h5py

from bson.json_util import dumps, loads
from bson.objectid import ObjectId

from flask import current_app as app, g


logger = app.logger
db = g.db


def rewrite_file_h5(file):
    old_data = h5py.File(file, "r")
    logger.debug("hdf5: open file " + file)

    experiment_id = os.path.basename(os.path.dirname(os.path.dirname(file)))
    logger.debug(experiment_id)
    new_data_path = os.path.abspath(os.path.join(os.path.dirname(file), experiment_id))
    if not os.path.exists(new_data_path):
        with h5py.File(os.path.abspath(os.path.join(os.path.dirname(file), experiment_id))) as  data:
            experiments = db['experiments']
            experiment_info = dumps(experiments.find({"_id": experiment_id}))
            data.attrs.create("exp_info", experiment_info.encode('utf8'))

            data.create_group("empty")
            data.create_group("dark")
            data.create_group("data")
            logger.debug("hdf5: created groups")

            frames = db['frames']
            for frame_id in old_data.keys():
                frame_info = dumps(frames.find({"_id": ObjectId(frame_id)}))
                json_frame = loads(frame_info)
                frame_number = str(json_frame[0]['frame']['number'])
                frame_type = str(json_frame[0]['frame']['mode'])
                frame_dataset = data[frame_type].create_dataset(frame_number, data=old_data[frame_id], compression="gzip", compression_opts=4)
                frame_dataset.attrs.create("frame_info", frame_info.encode('utf8'))

            logger.debug("hdf5: wrote compressed datasets")
            data.flush()

    else:
        logger.debug("file already exists")


experiments_path = os.path.join('data', 'experiments')
for root, dirs, files in os.walk(experiments_path):
    if 'frames.h5' in files:
        rewrite_file_h5(os.path.join(root, 'frames.h5'))
