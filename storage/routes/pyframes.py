import json
import os
from threading import Thread

import h5py
import matplotlib
import portalocker
import scipy.ndimage

matplotlib.use('Agg')
import matplotlib.pyplot as plt

from flask import current_app as app

logger = app.logger


def add_frame(frame, frame_info, frame_number, frame_type, frame_id, experiment_id):
    frames_file_path = os.path.join('data', 'experiments', str(experiment_id), 'before_processing', '{}.h5'.format(experiment_id))

    # Extract detector info from frame_info JSON
    try:
        frame_info_dict = json.loads(frame_info)
        # frame_info is a MongoDB document; the original event wraps it in a 'frame' key
        frame_payload = frame_info_dict.get('frame', frame_info_dict)
        detector_info = frame_payload.get('image_data', {}).get('detector', {})
        detector_model = str(detector_info.get('model', ''))
        pixel_size = float(detector_info.get('pixel_size', 4.25e-3))
    except (ValueError, TypeError, AttributeError):
        detector_model = ''
        pixel_size = 4.25e-3

    lock_path = frames_file_path + '.lock'
    with portalocker.Lock(lock_path, timeout=60):
        with h5py.File(frames_file_path, 'r+') as frames_file:
            frames_file[frame_type].create_dataset(str(frame_number), data=frame, compression="gzip", compression_opts=4)
            ds = frames_file[frame_type][str(frame_number)]
            ds.attrs["frame_info"] = frame_info.encode('utf8')
            ds.attrs["detector_model"] = detector_model
            ds.attrs["pixel_size"] = pixel_size

    logger.info('hdf5 file: add frame {} to experiment {} successfully'.format(frame_id, experiment_id))

    png_file_path = os.path.abspath(os.path.join('data', 'experiments', str(experiment_id), 'before_processing', 'png',
                                 str(frame_id) + '.png'))
    Thread(target=make_png, args=(frame, png_file_path)).start()
    logger.info('png: start making png from frame {} of experiment {}'.format(frame_id, experiment_id))

# TODO: remove method as unused
def delete_frame(frame_number, frame_type, frame_id,  experiment_id):
    frames_file_path = os.path.join('data', 'experiments', str(experiment_id), 'before_processing', '{}.h5'.format(experiment_id))
    with h5py.File(frames_file_path, 'r+') as frames_file:
        del frames_file[frame_type][str(frame_number)]
    logger.info(
        'hdf5 file: frame {} was deleted from experiment {} successfully'.format(str(frame_id), str(experiment_id)))


def make_png(frame, png_path):
    logger.info('Going to make png...')
    # Downsample 4x before filtering — reduces image from e.g. 4096x4096 to 1024x1024
    # This makes median_filter ~16x faster with negligible quality loss for preview
    small = frame[::4, ::4]
    enhanced_image = scipy.ndimage.filters.median_filter(small, size=3)
    fig = plt.figure(figsize=(7, 4), dpi=72)
    ax = fig.add_subplot(111)
    im = ax.imshow(enhanced_image, cmap=plt.cm.gray)
    fig.colorbar(im)
    fig.tight_layout()
    fig.savefig(png_path, dpi=72)
    plt.close(fig)
    logger.info('png was made')
