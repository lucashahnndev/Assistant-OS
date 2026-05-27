import React from 'react';

const StitchBackground = () => {
    return (
        <div className="absolute inset-0 overflow-hidden bg-[#05020a] z-[-1] pointer-events-none">
            <style>
                {`
                @keyframes pulse-blob-1 {
                    0%, 100% { transform: scale(1) translate(0, 0); opacity: 0.5; }
                    50% { transform: scale(1.1) translate(5%, 5%); opacity: 0.7; }
                }
                @keyframes pulse-blob-2 {
                    0%, 100% { transform: scale(1) translate(0, 0); opacity: 0.4; }
                    50% { transform: scale(1.2) translate(-5%, -5%); opacity: 0.6; }
                }
                @keyframes pulse-blob-3 {
                    0%, 100% { transform: scale(1) translate(0, 0); opacity: 0.4; }
                    50% { transform: scale(1.15) translate(5%, -5%); opacity: 0.6; }
                }
                .animate-blob-1 { animation: pulse-blob-1 12s infinite ease-in-out; }
                .animate-blob-2 { animation: pulse-blob-2 15s infinite ease-in-out; }
                .animate-blob-3 { animation: pulse-blob-3 18s infinite ease-in-out; }
                `}
            </style>

            {/* Glowing Blobs */}
            <div className="absolute top-[-15%] left-[-10%] w-[60%] h-[70%] bg-purple-700 rounded-full mix-blend-screen opacity-50 blur-[130px] animate-blob-1"></div>
            <div className="absolute top-[20%] right-[-10%] w-[55%] h-[65%] bg-cyan-600 rounded-full mix-blend-screen opacity-40 blur-[140px] animate-blob-2"></div>
            <div className="absolute bottom-[-20%] left-[15%] w-[70%] h-[75%] bg-pink-600 rounded-full mix-blend-screen opacity-40 blur-[150px] animate-blob-3"></div>
            
            {/* Dot Grid Overlay */}
            <div 
                className="absolute inset-0 opacity-[0.15]"
                style={{
                    backgroundImage: 'radial-gradient(circle, #ffffff 1px, transparent 1px)',
                    backgroundSize: '24px 24px'
                }}
            ></div>
        </div>
    );
};

export default StitchBackground;
