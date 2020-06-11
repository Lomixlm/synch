import logging
import signal
from signal import Signals

from mysql2ch.redis import RedisBroker, RedisLogPos

from .factory import Global

logger = logging.getLogger("mysql2ch.producer")


def produce(args):
    settings = Global.settings
    reader = Global.reader

    pos_handler = RedisLogPos()

    broker = RedisBroker()

    def signal_handler(signum: Signals, handler):
        sig = Signals(signum)
        log_f, log_p = pos_handler.get_log_pos()
        broker.close()
        logger.info(f"shutdown producer on {sig.name}, current position: {log_f}:{log_p}")
        exit()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    log_file, log_pos = pos_handler.get_log_pos()
    if not (log_file and log_pos):
        log_file = settings.init_binlog_file
        log_pos = settings.init_binlog_pos
        pos_handler.set_log_pos_slave(log_file, log_pos)
    else:
        log_pos = int(log_pos)

    logger.info(f"start producer success")
    count = 0
    tables = []
    schema_table = settings.schema_table
    for k, v in schema_table.items():
        tables += v
    only_schemas = list(schema_table.keys())
    only_tables = list(set(tables))

    for schema, table, event, file, pos in reader.binlog_reading(
        only_tables=only_tables,
        only_schemas=only_schemas,
        log_file=log_file,
        log_pos=log_pos,
        server_id=settings.mysql_server_id,
        skip_dmls=settings.skip_dmls,
        skip_delete_tables=settings.skip_delete_tables,
        skip_update_tables=settings.skip_update_tables,
    ):
        if not schema_table.get(schema) or (table and table not in schema_table.get(schema)):
            continue
        broker.send(msg=event, schema=schema)
        pos_handler.set_log_pos_slave(file, pos)

        if count == settings.insert_interval:
            count = 0
            logger.info(f"success send {settings.insert_interval} events")
        count += 1
        logger.debug(f"send to queue success: key:{schema},event:{event}")
        logger.debug(f"success set binlog pos:{file}:{pos}")
