// static/js/utils.js

/**
 * Formats a UNIX timestamp into a full date and time string (e.g., "DD/MM/YYYY HH:MM:SS").
 * @param {number} unixTimestamp - The UNIX timestamp in seconds.
 * @returns {string} The formatted date and time string.
 */
const formatUnixTimestamp = (unixTimestamp) => {
    return `${formatDateFromUnix(unixTimestamp)} ${formatTimeFromUnix(unixTimestamp)}`;
};

/**
 * Formats a UNIX timestamp into a date string (e.g., "DD/MM/YYYY").
 * @param {number} unixTimestamp - The UNIX timestamp in seconds.
 * @returns {string} The formatted date string.
 */
const formatDateFromUnix = (unixTimestamp) => {
    const date = new Date(unixTimestamp * 1000);
    const pad = (n) => n.toString().padStart(2, '0');
    const day = pad(date.getDate());
    const month = pad(date.getMonth() + 1); // getMonth() is zero-based
    const year = date.getFullYear();
    return `${day}/${month}/${year}`;
};

/**
 * Formats a UNIX timestamp into a time string (e.g., "HH:MM:SS").
 * @param {number} unixTimestamp - The UNIX timestamp in seconds.
 * @returns {string} The formatted time string.
 */
const formatTimeFromUnix = (unixTimestamp) => {
    const date = new Date(unixTimestamp * 1000);
    const pad = (n) => n.toString().padStart(2, '0');
    const hours = pad(date.getHours());
    const minutes = pad(date.getMinutes());
    const seconds = pad(date.getSeconds());
    return `${hours}:${minutes}:${seconds}`;
};

/**
 * Converts a number of bytes into a human-readable string with appropriate units.
 * @param {number} b - The number of bytes.
 * @param {number} [d=2] - The number of decimal places to use.
 * @returns {string} The formatted string (e.g., "1.23 MB").
 */
const formatBytes = (b, d = 2) => {
    // Handles invalid, negative, or non-finite values.
    if (b < 0 || !isFinite(b)) return "N/A";
    if (b === 0) return "0 Bytes";

    const k = 1024;
    const sizes = ["Bytes", "KB", "MB", "GB", "TB", "PB"];
    
    // Calculate the size index (e.g., 0 for Bytes, 1 for KB, etc.).
    // Math.log(b) / Math.log(k) is the base-k logarithm of b, which gives the power.
    const i = Math.floor(Math.log(b) / Math.log(k));

    // If the index is valid, format the number.
    // Otherwise (if for some reason i is out of range), return the value in Bytes.
    if (i >= 0 && i < sizes.length) {
        const value = b / Math.pow(k, i);
        return `${parseFloat(value.toFixed(d))} ${sizes[i]}`;
    }

    return `${b.toFixed(d)} Bytes`;
};
