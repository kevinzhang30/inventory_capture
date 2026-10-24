/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  images: { unoptimized: true }, // capture images are short-lived presigned S3 URLs
};

export default nextConfig;
