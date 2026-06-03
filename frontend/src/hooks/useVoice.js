import { useState, useRef, useCallback } from 'react';
import { MicVAD } from '@ricky0123/vad-web';

const VAD_NOISE_PROFILE = {
    positiveSpeechThreshold: 0.78,
    negativeSpeechThreshold: 0.58,
    redemptionMs: 1200,
    preSpeechPadMs: 160,
    minSpeechMs: 450
};

const MIC_CONSTRAINTS = {
    audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1
    }
};

const getVadAssetBasePath = () => `${window.location.origin}/node_modules/@ricky0123/vad-web/dist/`;
const getOrtWasmBasePath = () => `${window.location.origin}/node_modules/onnxruntime-web/dist/`;

/**
 * useVoice Hook
 * Enables voice capture and streams speech segments to backend.
 * Primary path: frontend VAD (@ricky0123/vad-web)
 * Fallback path: legacy ScriptProcessor streaming
 */
export function useVoice({ sessionId, sendMessage, onTranscriptionResult, onError }) {
    const [isRecording, setIsRecording] = useState(false);
    const [intensity, setIntensity] = useState(0);
    const mediaRecorderRef = useRef(null);
    const audioStreamRef = useRef(null);
    const vadRef = useRef(null);
    const vadReadyRef = useRef(false);
    const segmentOpenRef = useRef(false);
    const liveStreamRef = useRef(null);
    const liveAudioContextRef = useRef(null);
    const liveSourceRef = useRef(null);
    const liveProcessorRef = useRef(null);
    const speechStartedAtRef = useRef(0);

    const emitVoiceState = useCallback((state, extra = {}) => {
        if (!sendMessage) return;
        try {
            sendMessage({
                type: 'voice.state',
                state,
                ...extra,
            });
        } catch (_) {
            // best-effort telemetry only
        }
    }, [sendMessage]);

    const sendPcm16AsChunks = useCallback((floatAudio) => {
        if (!floatAudio || !floatAudio.length) return;
        const pcm16 = new Int16Array(floatAudio.length);
        for (let i = 0; i < floatAudio.length; i++) {
            const s = Math.max(-1, Math.min(1, floatAudio[i]));
            pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
        }

        const samplesPerChunk = 4096;
        for (let offset = 0; offset < pcm16.length; offset += samplesPerChunk) {
            const chunk = pcm16.subarray(offset, Math.min(offset + samplesPerChunk, pcm16.length));
            const bytes = new Uint8Array(chunk.buffer, chunk.byteOffset, chunk.byteLength);
            let binary = '';
            const step = 0x8000;
            for (let i = 0; i < bytes.length; i += step) {
                binary += String.fromCharCode(...bytes.subarray(i, i + step));
            }
            const base64 = window.btoa(binary);
            sendMessage({
                type: 'input.audio.chunk',
                b64: base64
            });
        }
    }, [sendMessage]);

    const stopLegacyPipeline = useCallback(() => {
        if (mediaRecorderRef.current) {
            try { mediaRecorderRef.current.stop(); } catch (_) { /* noop */ }
            mediaRecorderRef.current = null;
        }
        if (audioStreamRef.current) {
            try {
                audioStreamRef.current.getTracks().forEach((track) => track.stop());
            } catch (_) { /* noop */ }
            audioStreamRef.current = null;
        }
    }, []);

    const stopLivePipeline = useCallback(() => {
        if (liveProcessorRef.current) {
            try { liveProcessorRef.current.disconnect(); } catch (_) { /* noop */ }
            liveProcessorRef.current = null;
        }
        if (liveSourceRef.current) {
            try { liveSourceRef.current.disconnect(); } catch (_) { /* noop */ }
            liveSourceRef.current = null;
        }
        if (liveAudioContextRef.current) {
            try {
                if (liveAudioContextRef.current.state !== 'closed') liveAudioContextRef.current.close();
            } catch (_) { /* noop */ }
            liveAudioContextRef.current = null;
        }
        if (liveStreamRef.current) {
            try { liveStreamRef.current.getTracks().forEach((t) => t.stop()); } catch (_) { /* noop */ }
            liveStreamRef.current = null;
        }
    }, []);

    const startLivePipeline = useCallback(async () => {
        const stream = await navigator.mediaDevices.getUserMedia(MIC_CONSTRAINTS);
        liveStreamRef.current = stream;

        const audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
        liveAudioContextRef.current = audioContext;
        const source = audioContext.createMediaStreamSource(stream);
        liveSourceRef.current = source;

        const processor = audioContext.createScriptProcessor(4096, 1, 1);
        liveProcessorRef.current = processor;
        source.connect(processor);
        processor.connect(audioContext.destination);

        processor.onaudioprocess = (e) => {
            if (!segmentOpenRef.current) return;
            const inputData = e.inputBuffer.getChannelData(0);
            sendPcm16AsChunks(inputData);
        };
    }, [sendPcm16AsChunks]);

    const startLegacyRecording = useCallback(async () => {
        const stream = await navigator.mediaDevices.getUserMedia(MIC_CONSTRAINTS);
        audioStreamRef.current = stream;

        const audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
        const source = audioContext.createMediaStreamSource(stream);

        const analyser = audioContext.createAnalyser();
        analyser.fftSize = 256;
        const dataArray = new Uint8Array(analyser.frequencyBinCount);
        source.connect(analyser);

        const processor = audioContext.createScriptProcessor(4096, 1, 1);
        source.connect(processor);
        processor.connect(audioContext.destination);

        let interval;
        mediaRecorderRef.current = {
            stop: () => {
                clearInterval(interval);
                processor.disconnect();
                source.disconnect();
                if (audioContext.state !== 'closed') audioContext.close();
            }
        };

        interval = setInterval(() => {
            analyser.getByteFrequencyData(dataArray);
            let sum = 0;
            const binCount = 10;
            for (let i = 0; i < binCount; i++) sum += dataArray[i];
            setIntensity(sum / binCount / 255);
        }, 50);

        sendMessage({
            type: 'session.start',
            sessionId,
            client: 'web',
            caps: { supportsBinaryAudio: false, supportsBargeIn: true }
        });

        sendMessage({
            type: 'input.audio.start',
            format: 'pcm16',
            sampleRate: 16000,
            channels: 1
        });
        segmentOpenRef.current = true;

        processor.onaudioprocess = (e) => {
            const inputData = e.inputBuffer.getChannelData(0);
            sendPcm16AsChunks(inputData);
        };
    }, [sendMessage, sendPcm16AsChunks, sessionId]);

    const startRecording = useCallback(async () => {
        if (!sendMessage) return false;

        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            const error = new Error("Microphone access is not supported or blocked (likely due to insecure HTTP context). Use localhost or HTTPS.");
            console.error(error);
            if (onError) onError(error);
            return false;
        }

        try {
            // Signal session start
            sendMessage({
                type: 'session.start',
                sessionId,
                client: 'web',
                caps: { supportsBinaryAudio: false, supportsBargeIn: true }
            });

            // Frontend VAD path (preferred)
            try {
                const vad = await MicVAD.new({
                    startOnLoad: false,
                    ...VAD_NOISE_PROFILE,
                    baseAssetPath: getVadAssetBasePath(),
                    onnxWASMBasePath: getOrtWasmBasePath(),
                    getStream: () => navigator.mediaDevices.getUserMedia(MIC_CONSTRAINTS),
                    onFrameProcessed: (_, frame) => {
                        if (!frame || !frame.length) return;
                        let sumSq = 0;
                        for (let i = 0; i < frame.length; i++) {
                            const v = frame[i];
                            sumSq += v * v;
                        }
                        const rms = Math.sqrt(sumSq / frame.length);
                        setIntensity(Math.min(1, rms * 8));
                    },
                    onSpeechStart: () => {
                        if (segmentOpenRef.current) return;
                        speechStartedAtRef.current = Date.now();
                        sendMessage({
                            type: 'input.audio.start',
                            format: 'pcm16',
                            sampleRate: 16000,
                            channels: 1
                        });
                        segmentOpenRef.current = true;
                    },
                    onSpeechEnd: () => {
                        if (!segmentOpenRef.current) return;
                        const speechMs = Date.now() - (speechStartedAtRef.current || Date.now());
                        speechStartedAtRef.current = 0;
                        sendMessage({ type: 'input.audio.end' });
                        segmentOpenRef.current = false;
                        if (speechMs >= VAD_NOISE_PROFILE.minSpeechMs && onTranscriptionResult) onTranscriptionResult();
                    },
                    onVADMisfire: () => {
                        speechStartedAtRef.current = 0;
                        if (segmentOpenRef.current) {
                            sendMessage({ type: 'input.audio.end' });
                            segmentOpenRef.current = false;
                        }
                    }
                });
                vadRef.current = vad;
                await startLivePipeline();
                await vad.start();
                vadReadyRef.current = true;
            } catch (vadError) {
                console.warn('VAD init failed; falling back to legacy audio pipeline:', vadError);
                emitVoiceState('vad_failed', { reason: 'vad_init_failed' });
                vadReadyRef.current = false;
                await startLegacyRecording();
            }

            setIsRecording(true);
            return true;
        } catch (error) {
            console.error('Error accessing microphone:', error);
            emitVoiceState('vad_failed', { reason: 'mic_error' });
            vadRef.current = null;
            vadReadyRef.current = false;
            stopLivePipeline();
            stopLegacyPipeline();
            segmentOpenRef.current = false;
            setIntensity(0);
            setIsRecording(false);
            if (onError) onError(error);
            return false;
        }
    }, [emitVoiceState, sessionId, sendMessage, onError, onTranscriptionResult, startLegacyRecording, startLivePipeline, stopLegacyPipeline, stopLivePipeline]);

    const stopRecording = useCallback(() => {
        const vad = vadRef.current;
        vadRef.current = null;
        const canDestroyVad = !!(
            vad
            && vadReadyRef.current
            && vad.initializationState === 'initialized'
            && vad.listening
            && vad._stream
            && vad._audioContext
            && vad._vadNode
            && vad._mediaStreamAudioSourceNode
        );

        if (canDestroyVad) {
            try {
                if (typeof vad.destroy === 'function') {
                    const maybeDestroy = vad.destroy();
                    if (maybeDestroy && typeof maybeDestroy.then === 'function') {
                        void maybeDestroy.catch(() => {});
                    }
                }
            } catch (_) { /* noop */ }
        } else {
            vadReadyRef.current = false;
            vadRef.current = null;
            stopLivePipeline();
            stopLegacyPipeline();
            if (segmentOpenRef.current) {
                sendMessage({ type: 'input.audio.end' });
                segmentOpenRef.current = false;
            }
        }
        vadReadyRef.current = false;
        stopLivePipeline();
        stopLegacyPipeline();
        if (segmentOpenRef.current) {
            sendMessage({ type: 'input.audio.end' });
            segmentOpenRef.current = false;
        }
        setIsRecording(false);
        setIntensity(0);
    }, [sendMessage, stopLegacyPipeline, stopLivePipeline]);

    const toggleRecording = useCallback(() => {
        if (isRecording) {
            stopRecording();
        } else {
            startRecording();
        }
    }, [isRecording, startRecording, stopRecording]);

    return {
        isRecording,
        intensity,
        startRecording,
        stopRecording,
        toggleRecording
    };
}
