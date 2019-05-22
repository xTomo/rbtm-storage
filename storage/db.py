import pymongo as pm
from flask import current_app as app, g

logger = app.logger

def get_db():
    if 'db' not in g:
        logger.info('init database')
        # TODO login and pass not secure
        client = pm.MongoClient(app.config['MONGODB_URI'])
        g.db = client["robotom"]

    return g.db
