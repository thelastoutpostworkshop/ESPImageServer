import pytest

from esp_image_server.display_commands import DisplayCommandStore


def queued(store):
    return store.queue_save('image.jpg', display_id='screen')


def test_cancellation_requires_board_confirmation_and_late_ack_cannot_reverse_it():
    store = DisplayCommandStore()
    save = queued(store)
    assert store.cancel(save['id'], display_id='other') is None
    assert store.cancel(save['id'], display_id='screen')['status'] == 'cancelling'
    stop = store.next('screen')
    assert stop['type'] == 'cancel_operation'
    store.cancel(save['id'], display_id='screen')
    assert store.next('screen')['id'] == stop['id']
    store.acknowledge(stop['id'], True, 'Save cancelled', display_id='screen')
    assert store.get(save['id'], display_id='screen')['status'] == 'cancelled'
    assert store.acknowledge(save['id'], True, 'late', display_id='screen')['status'] == 'cancelled'
    assert store.next('screen') is None


def test_committed_save_wins_when_cancellation_arrived_too_late():
    store = DisplayCommandStore()
    save = queued(store)
    store.cancel(save['id'], display_id='screen')
    stop = store.next('screen')
    store.acknowledge(save['id'], True, 'Saved image.jpg', display_id='screen')
    store.acknowledge(stop['id'], True, 'Save cancelled', display_id='screen')
    assert store.get(save['id'], display_id='screen')['status'] == 'complete'


@pytest.mark.parametrize('cancel_first', [False, True])
def test_new_command_supersedes_save_even_if_old_ack_arrives(cancel_first):
    store = DisplayCommandStore()
    save = queued(store)
    if cancel_first:
        store.cancel(save['id'], display_id='screen')
    replacement = store.queue('display_sd_file', filename='other.jpg', display_id='screen')
    assert store.acknowledge(save['id'], True, 'late', display_id='screen')['status'] == 'superseded'
    assert store.next('screen') == replacement


def test_progress_is_isolated_and_does_not_imply_success():
    store = DisplayCommandStore()
    save = queued(store)
    assert store.progress(save['id'], 'verifying', 10, 10, display_id='other') is None
    progress = store.progress(save['id'], 'verifying', 10, 10, display_id='screen')
    assert progress['status'] == 'pending'
    assert progress['progress']['stage'] == 'verifying'
    store.acknowledge(save['id'], False, 'Read-back failed', display_id='screen')
    assert store.progress(save['id'], 'downloading', 1, 10, display_id='screen')['status'] == 'failed'


@pytest.mark.parametrize('stage,received,total', [('done', 1, 1), ('downloading', -1, 1), ('downloading', 2, 1), ('verifying', 1, 64 * 1024 * 1024 + 1)])
def test_invalid_progress_rejected(stage, received, total):
    with pytest.raises(ValueError):
        DisplayCommandStore().progress('id', stage, received, total, display_id='screen')


@pytest.mark.parametrize('verified_saves,verified,expected', [(False, None, False), (True, None, False), (True, False, False), (True, True, True)])
def test_reuse_always_requires_per_file_verification(verified_saves, verified, expected):
    store = DisplayCommandStore()
    store.report_sd_card({'available': True, 'verified_saves': verified_saves, 'files': [
        {'name': 'esp-image-hash.jpg', 'type': 'image', 'content_key': 'v1-hash', 'verified': verified},
        {'name': 'esp-video-abcdefgh-fps8.mjpeg', 'type': 'video', 'content_key': 'v2-video', 'verified': verified},
    ]}, display_id='screen')
    assert bool(store.find_sd_card_image('hash', display_id='screen')) == expected
    assert bool(store.find_sd_card_content('v1-hash', 'image', display_id='screen')) == expected
    assert bool(store.find_sd_card_content('v2-video', 'video', display_id='screen')) == expected
    assert store.find_sd_card_content('unknown-key', 'video', display_id='screen') is None


@pytest.mark.parametrize('name,media_type,key', [
    ('esp-image-hash.jpg', 'image', 'v1-hash'),
    ('esp-image-20260912-131013-v1-hash.jpg', 'image', 'v1-hash'),
    ('esp-video-abcdefgh-fps8.mjpeg', 'video', 'v1-abcdefgh-320x820-fps8'),
    ('esp-video-20260912-131013-v1-abcdefgh-320x820-fps8.mjpeg', 'video', 'v1-abcdefgh-320x820-fps8'),
])
def test_filenames_without_content_keys_never_allow_reuse(name, media_type, key):
    store = DisplayCommandStore()
    store.report_sd_card({'available': True, 'files': [
        {'name': name, 'type': media_type, 'verified': True},
    ]}, display_id='screen')
    assert store.find_sd_card_content(key, media_type, display_id='screen') is None
    if media_type == 'image':
        assert store.find_sd_card_image('hash', display_id='screen') is None
