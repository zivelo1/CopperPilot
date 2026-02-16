# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Celery configuration for background task processing
Handles long-running circuit generation tasks
"""
from celery import Celery
from kombu import Queue
from server.config import config
import logging

logger = logging.getLogger(__name__)

# Create Celery app
celery_app = Celery(
    'circuit_automation',
    broker=config.REDIS_URL,
    backend=config.REDIS_URL,
    include=['workflow.tasks']  # Import task modules
)

# Celery configuration
celery_app.conf.update(
    # Task settings
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,

    # Queue configuration
    task_default_queue='circuit_generation',
    task_queues=(
        Queue('circuit_generation', routing_key='circuit.*'),
        Queue('high_priority', routing_key='priority.*'),
        Queue('converters', routing_key='convert.*'),
    ),

    # Task routing
    task_routes={
        'workflow.generate_circuit': {'queue': 'circuit_generation'},
        'workflow.fix_circuit': {'queue': 'high_priority'},
        'workflow.convert_format': {'queue': 'converters'},
    },

    # Worker settings
    worker_prefetch_multiplier=1,  # Process one task at a time
    worker_max_tasks_per_child=10,  # Restart worker after 10 tasks (prevent memory leaks)

    # Result backend settings
    result_expires=3600,  # Results expire after 1 hour

    # Error handling
    task_acks_late=True,  # Acknowledge task after completion
    task_reject_on_worker_lost=True,

    # Monitoring
    worker_send_task_events=True,
    task_send_sent_event=True,
)

# Task base name
celery_app.conf.task_default_routing_key = 'circuit.default'

# Beat schedule for periodic tasks (if needed)
celery_app.conf.beat_schedule = {
    'cleanup-old-projects': {
        'task': 'workflow.tasks.cleanup_old_projects',
        'schedule': 3600.0,  # Every hour
    },
}

if __name__ == '__main__':
    # Run worker
    celery_app.start()