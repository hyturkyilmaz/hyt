/**
 * HYT Content Automation - Admin JavaScript
 * Handles: drag-drop upload, AJAX calls, queue refresh, settings UI
 */
/* global hytCA, jQuery */
(function ($) {
    'use strict';

    const CA = window.hytCA || {};

    /* =======================================================================
       Utility helpers
       =================================================================== */

    function ajaxRequest(action, data, callback) {
        const payload = Object.assign({ action: action, nonce: CA.nonce }, data);
        $.post(CA.ajaxUrl, payload, function (response) {
            if (typeof callback === 'function') {
                callback(response);
            }
        }).fail(function () {
            console.error('AJAX request failed:', action);
        });
    }

    function showNotice(selector, message, type) {
        const $el = $(selector);
        $el.removeClass('success error')
           .addClass(type)
           .html(message)
           .show();
        if (type === 'success') {
            setTimeout(function () { $el.fadeOut(); }, 5000);
        }
    }

    function showInlineNotice(selector, message, type) {
        showNotice(selector, message, type);
    }

    /* =======================================================================
       Upload Section (Dashboard)
       =================================================================== */

    var selectedFiles = [];

    function initUpload() {
        var $dropZone   = $('#hyt-drop-zone');
        var $fileInput  = $('#hyt-file-input');
        var $uploadBtn  = $('#hyt-upload-btn');
        var $fileList   = $('#hyt-file-list');
        var $fileCount  = $('#hyt-file-count');

        if (!$dropZone.length) return;

        // Click on drop zone opens file picker
        $dropZone.on('click', function (e) {
            if (!$(e.target).hasClass('hyt-remove-file') &&
                !$(e.target).closest('.hyt-remove-file').length) {
                $fileInput.trigger('click');
            }
        });

        // Drag events
        $dropZone.on('dragover dragenter', function (e) {
            e.preventDefault();
            e.stopPropagation();
            $(this).addClass('hyt-drag-over');
        });

        $dropZone.on('dragleave dragend drop', function (e) {
            e.preventDefault();
            e.stopPropagation();
            $(this).removeClass('hyt-drag-over');
        });

        $dropZone.on('drop', function (e) {
            var files = e.originalEvent.dataTransfer.files;
            addFiles(files);
        });

        // File input change
        $fileInput.on('change', function () {
            addFiles(this.files);
            this.value = ''; // reset so same file can be picked again
        });

        // Upload button
        $uploadBtn.on('click', function () {
            if (selectedFiles.length === 0) return;
            uploadFiles();
        });

        function addFiles(fileList) {
            var allowed = ['docx', 'txt'];
            Array.from(fileList).forEach(function (file) {
                var ext = file.name.split('.').pop().toLowerCase();
                if (allowed.indexOf(ext) === -1) return;
                // Avoid duplicates by name+size
                var exists = selectedFiles.some(function (f) {
                    return f.name === file.name && f.size === file.size;
                });
                if (!exists) {
                    selectedFiles.push(file);
                }
            });
            renderFileList();
        }

        function renderFileList() {
            $fileList.empty();
            selectedFiles.forEach(function (file, index) {
                var ext  = file.name.split('.').pop().toLowerCase();
                var icon = ext === 'docx' ? 'media-document' : 'media-text';
                var size = formatFileSize(file.size);
                var item = $(
                    '<div class="hyt-file-list-item">' +
                    '<span class="dashicons dashicons-' + icon + '"></span>' +
                    '<span class="hyt-fname">' + escHtml(file.name) + '</span>' +
                    '<span style="margin-left:6px;color:#646970;font-size:12px;">(' + size + ')</span>' +
                    '<span class="dashicons dashicons-no hyt-remove-file" data-index="' + index + '"></span>' +
                    '</div>'
                );
                $fileList.append(item);
            });

            var count = selectedFiles.length;
            $fileCount.text(count > 0 ? count + ' dosya seçildi' : '');
            $uploadBtn.prop('disabled', count === 0);
        }

        $fileList.on('click', '.hyt-remove-file', function (e) {
            e.stopPropagation();
            var idx = parseInt($(this).data('index'), 10);
            selectedFiles.splice(idx, 1);
            renderFileList();
        });

        function uploadFiles() {
            if (selectedFiles.length === 0) return;

            var $progress = $('#hyt-upload-progress');
            var $bar      = $('#hyt-progress-bar');
            var $text     = $('#hyt-progress-text');
            var $result   = $('#hyt-upload-result');

            $progress.show();
            $result.hide();
            $uploadBtn.prop('disabled', true);

            var total     = selectedFiles.length;
            var done      = 0;
            var processed = 0;
            var errors    = [];

            // Batch upload: send all files in one FormData
            // (if too large, split into batches of 50)
            var batchSize = 50;
            var batches   = [];
            for (var i = 0; i < selectedFiles.length; i += batchSize) {
                batches.push(selectedFiles.slice(i, i + batchSize));
            }

            function uploadBatch(batchIndex) {
                if (batchIndex >= batches.length) {
                    // All done
                    $bar.css('width', '100%');
                    $text.text(total + ' / ' + total + ' dosya yüklendi');

                    var msg = processed + ' dosya başarıyla işleme alındı.';
                    if (errors.length > 0) {
                        msg += '\nHatalar: ' + errors.join(', ');
                    }

                    $result.removeClass('success error')
                           .addClass(errors.length > 0 && processed === 0 ? 'error' : 'success')
                           .html('<strong>' + processed + '</strong> dosya kuyruğa eklendi.' +
                                 (errors.length > 0 ? '<br><small>Hatalar: ' + escHtml(errors.join('; ')) + '</small>' : ''))
                           .show();

                    selectedFiles = [];
                    renderFileList();
                    $uploadBtn.prop('disabled', true);

                    // Refresh queue table after 2s
                    setTimeout(refreshRecentQueue, 2000);
                    return;
                }

                var batch = batches[batchIndex];
                var formData = new FormData();
                formData.append('action', 'hyt_upload_files');
                formData.append('nonce', CA.nonce);
                batch.forEach(function (file) {
                    formData.append('files[]', file, file.name);
                });

                var xhr = new XMLHttpRequest();
                xhr.open('POST', CA.ajaxUrl, true);

                xhr.upload.onprogress = function (e) {
                    if (e.lengthComputable) {
                        var batchProgress = (e.loaded / e.total) * 100;
                        var overallDone   = (batchIndex / batches.length) * 100;
                        var batchPortion  = (1 / batches.length) * batchProgress;
                        $bar.css('width', Math.min(99, overallDone + batchPortion) + '%');
                    }
                };

                xhr.onload = function () {
                    var response;
                    try {
                        response = JSON.parse(xhr.responseText);
                    } catch (ex) {
                        response = { success: false };
                    }

                    if (response && response.success && response.data) {
                        processed += response.data.processed || 0;
                        if (response.data.errors) {
                            errors = errors.concat(response.data.errors);
                        }
                    }

                    done += batch.length;
                    $text.text(done + ' / ' + total + ' dosya gönderildi');
                    uploadBatch(batchIndex + 1);
                };

                xhr.onerror = function () {
                    errors.push('Batch ' + (batchIndex + 1) + ': Ağ hatası');
                    done += batch.length;
                    uploadBatch(batchIndex + 1);
                };

                xhr.send(formData);
            }

            uploadBatch(0);
        }
    }

    /* =======================================================================
       Queue Refresh
       =================================================================== */

    var queueRefreshTimer = null;

    function startQueueRefresh() {
        if (queueRefreshTimer) return;
        queueRefreshTimer = setInterval(function () {
            if ($('.hyt-badge-processing').length > 0 || $('.hyt-badge-pending').length > 0) {
                refreshRecentQueue();
            } else {
                clearInterval(queueRefreshTimer);
                queueRefreshTimer = null;
            }
        }, 30000);
    }

    function refreshRecentQueue() {
        // Reload only the stats row and table if on dashboard
        if (CA.currentPage === 'hyt-ca-dashboard') {
            window.location.reload();
        }
    }

    /* =======================================================================
       Retry / Cancel Buttons
       =================================================================== */

    function initQueueActions() {
        // Retry
        $(document).on('click', '.hyt-btn-retry', function () {
            var $btn = $(this);
            var id   = $btn.data('id');
            if (!confirm(CA.strings.confirmRetry)) return;

            $btn.prop('disabled', true).text(CA.strings.processing);

            ajaxRequest('hyt_retry_item', { id: id }, function (response) {
                if (response && response.success) {
                    location.reload();
                } else {
                    alert('Hata: ' + (response && response.data && response.data.message ? response.data.message : 'Bilinmeyen hata'));
                    $btn.prop('disabled', false).text('Tekrar');
                }
            });
        });

        // Cancel
        $(document).on('click', '.hyt-btn-cancel', function () {
            var $btn = $(this);
            var id   = $btn.data('id');
            if (!confirm(CA.strings.confirmCancel)) return;

            $btn.prop('disabled', true);

            ajaxRequest('hyt_cancel_item', { id: id }, function (response) {
                if (response && response.success) {
                    var $row = $btn.closest('tr');
                    if ($row.length) {
                        $row.fadeOut(300, function () { $row.remove(); });
                    }
                } else {
                    alert('İptal edilemedi.');
                    $btn.prop('disabled', false);
                }
            });
        });

        // Retry all failed
        $('#hyt-retry-all-failed').on('click', function () {
            var $btn = $(this);
            $btn.prop('disabled', true).prepend('<span class="hyt-spinner"></span>');

            ajaxRequest('hyt_retry_all_failed', {}, function (response) {
                $btn.prop('disabled', false).find('.hyt-spinner').remove();
                if (response && response.success) {
                    showInlineNotice('#hyt-bulk-result', response.data.message, 'success');
                    setTimeout(function () { location.reload(); }, 1500);
                } else {
                    showInlineNotice('#hyt-bulk-result', 'Hata oluştu.', 'error');
                }
            });
        });
    }

    /* =======================================================================
       Google Drive Scan
       =================================================================== */

    function initDriveScan() {
        $('#hyt-gdrive-scan-btn').on('click', function () {
            var $btn    = $(this);
            var $result = $('#hyt-gdrive-scan-result');

            $btn.prop('disabled', true)
                .html('<span class="hyt-spinner"></span> Taranıyor...');

            ajaxRequest('hyt_gdrive_scan', {}, function (response) {
                $btn.prop('disabled', false)
                    .html('<span class="dashicons dashicons-search"></span> Drive Klasörünü Tara');

                if (response && response.success) {
                    var d = response.data;
                    var msg = d.added + ' yeni dosya eklendi.';
                    if (d.errors && d.errors.length > 0) {
                        msg += ' Hatalar: ' + d.errors.join('; ');
                    }
                    $result.removeClass('error').addClass('success').html(msg).show();
                } else {
                    var errMsg = (response && response.data && response.data.message)
                        ? response.data.message : 'Bilinmeyen hata';
                    $result.removeClass('success').addClass('error').html(errMsg).show();
                }
            });
        });

        // Connect button (on settings page)
        $('#hyt-gdrive-connect-btn').on('click', function () {
            var $btn = $(this);
            $btn.prop('disabled', true);

            ajaxRequest('hyt_gdrive_connect', {}, function (response) {
                $btn.prop('disabled', false);
                if (response && response.success && response.data && response.data.auth_url) {
                    window.location.href = response.data.auth_url;
                } else {
                    showInlineNotice('#hyt-gdrive-result',
                        (response && response.data && response.data.message) ? response.data.message : 'Hata',
                        'error');
                }
            });
        });

        // Disconnect
        $('#hyt-gdrive-disconnect-btn').on('click', function () {
            if (!confirm('Google Drive bağlantısını kesmek istiyor musunuz?')) return;
            var $btn = $(this);
            $btn.prop('disabled', true);

            ajaxRequest('hyt_gdrive_disconnect', {}, function (response) {
                if (response && response.success) {
                    location.reload();
                } else {
                    $btn.prop('disabled', false);
                }
            });
        });
    }

    /* =======================================================================
       Claude Test
       =================================================================== */

    function initClaudeTest() {
        $('#hyt-test-claude-btn').on('click', function () {
            var $btn    = $(this);
            var $result = $('#hyt-test-claude-result');

            $btn.prop('disabled', true)
                .html('<span class="hyt-spinner"></span> ' + CA.strings.testingApi);

            ajaxRequest('hyt_test_claude', {}, function (response) {
                $btn.prop('disabled', false)
                    .html('<span class="dashicons dashicons-controls-play"></span> Bağlantıyı Test Et');

                if (response && response.success) {
                    showInlineNotice('#hyt-test-claude-result',
                        '✓ ' + response.data.message, 'success');
                } else {
                    var msg = (response && response.data && response.data.message)
                        ? response.data.message : 'Bağlantı başarısız';
                    showInlineNotice('#hyt-test-claude-result', '✗ ' + msg, 'error');
                }
            });
        });
    }

    /* =======================================================================
       Settings Save
       =================================================================== */

    function initSettingsSave() {
        // Generic save button handler
        $(document).on('click', '[id^="hyt-save-"][id$="-settings"]', function () {
            var $btn   = $(this);
            var tab    = $btn.data('tab');
            var data   = { tab: tab };

            $btn.prop('disabled', true)
                .prepend('<span class="hyt-spinner"></span>');

            // Collect form data based on tab
            switch (tab) {
                case 'api':
                    data.claude_api_key = $('#claude_api_key').val();
                    data.claude_model   = $('#claude_model').val();
                    break;
                case 'gdrive':
                    data.gdrive_client_id     = $('#gdrive_client_id').val();
                    data.gdrive_client_secret = $('#gdrive_client_secret').val();
                    data.gdrive_folder_id     = $('#gdrive_folder_id').val();
                    data.gdrive_frequency     = $('#gdrive_frequency').val();
                    break;
                case 'schedule':
                    data.schedule_time     = $('#schedule_time').val();
                    data.schedule_author   = $('#schedule_author').val();
                    data.schedule_category = $('#schedule_category').val();
                    // Collect checked days
                    var days = [];
                    $('.hyt-day-checkbox:checked').each(function () {
                        days.push($(this).val());
                    });
                    data['schedule_days[]'] = days;
                    break;
                case 'holidays':
                    data.holiday_dates = $('#holiday_dates').val();
                    break;
            }

            ajaxRequest('hyt_save_settings', data, function (response) {
                $btn.prop('disabled', false).find('.hyt-spinner').remove();

                if (response && response.success) {
                    showInlineNotice('#hyt-settings-notice', '✓ ' + CA.strings.saved, 'success');
                } else {
                    var msg = (response && response.data && response.data.message)
                        ? response.data.message : 'Kaydetme başarısız';
                    showInlineNotice('#hyt-settings-notice', '✗ ' + msg, 'error');
                }
            });
        });
    }

    /* =======================================================================
       API Key Show/Hide Toggle
       =================================================================== */

    function initApiKeyToggle() {
        $('#hyt-toggle-api-key').on('click', function () {
            var $input = $('#claude_api_key');
            var isPass = $input.attr('type') === 'password';
            $input.attr('type', isPass ? 'text' : 'password');
            $(this).find('.dashicons')
                .toggleClass('dashicons-visibility', !isPass)
                .toggleClass('dashicons-hidden', isPass);
        });
    }

    /* =======================================================================
       Helpers
       =================================================================== */

    function escHtml(str) {
        return $('<div>').text(String(str)).html();
    }

    function formatFileSize(bytes) {
        if (bytes < 1024)        return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    }

    /* =======================================================================
       Init
       =================================================================== */

    $(document).ready(function () {
        initUpload();
        initQueueActions();
        initDriveScan();
        initClaudeTest();
        initSettingsSave();
        initApiKeyToggle();

        // Auto-refresh queue if processing items exist
        if ($('.hyt-badge-processing').length > 0 || $('.hyt-badge-pending').length > 0) {
            startQueueRefresh();
        }
    });

}(jQuery));
