import os, shutil, h5py
import json

from flask import current_app as app

from .hdf5_v2 import create_experiment_hdf5_v2


logger = app.logger


def create_experiment(experiment_id, exp_info, use_v2=True):
    """
    Создаёт структуру эксперимента в файловой системе.
    
    Args:
        experiment_id: UUID эксперимента
        exp_info: JSON-строка с метаданными эксперимента (MongoDB документ)
        use_v2: Если True — создаёт HDF5 v2 формат, иначе — legacy v1
        
    Returns:
        True если успешно, False если эксперимент уже существует
    """
    experiment_path = os.path.join('data', 'experiments', str(experiment_id))

    if not os.path.exists(experiment_path):
        os.makedirs(experiment_path)
        before_processing_path = os.path.join(experiment_path, 'before_processing')
        os.makedirs(before_processing_path)

        png_before_processing_path = os.path.join(before_processing_path, "png")
        os.makedirs(png_before_processing_path)

        after_processing_path = os.path.join(experiment_path, 'after_processing')
        os.makedirs(after_processing_path)

        reconstructions_path = os.path.join(experiment_path, 'reconstructions')
        os.makedirs(reconstructions_path)

        vis_path = os.path.join(experiment_path, '3d')
        os.makedirs(vis_path)

        if use_v2:
            # Создаём HDF5 v2 формат
            params = json.loads(exp_info)
            create_experiment_hdf5_v2(experiment_id, params)
        else:
            # Legacy v1 формат
            frames_file_path = os.path.join(before_processing_path, '{}.h5'.format(experiment_id))
            with h5py.File(frames_file_path, 'w') as frames_file:
                frames_file.create_group("empty")
                frames_file.create_group("dark")
                frames_file.create_group("data")
                frames_file.create_group("data_check")
                frames_file.attrs["exp_info"] = exp_info.encode("utf-8")

        logger.info(f'file system: create experiment {experiment_id} successfully (v2={use_v2})')
        return True
    else:
        logger.warning(f'file system: experiment {experiment_id} already exists')
        return False


def delete_experiment(experiment_id):
    experiment_path = os.path.join('data', 'experiments', str(experiment_id))
    if os.path.exists(experiment_path):
        shutil.rmtree(experiment_path)
        logger.info('file system: delete experiment {} successfully'.format(experiment_id))
        return True
    else:
        logger.warning('file system: cant find experiment {} for deleting'.format(experiment_id))
        return False