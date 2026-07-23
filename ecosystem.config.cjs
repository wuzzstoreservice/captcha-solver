module.exports = {
  apps: [
    {
      name: 'captcha-solver',
      cwd: '/root/captcha-solver',
      script: './run.sh',
      interpreter: 'bash',
      autorestart: true,
      max_memory_restart: '1500M',
      env: {
        PYTHONUNBUFFERED: '1',
        CAPTCHA_SOLVER_HOST: '127.0.0.1',
        CAPTCHA_SOLVER_PORT: '5080',
        CAPTCHA_SOLVER_THREAD: '1',
        CAPTCHA_SOLVER_HEADLESS: 'true',
        CAPTCHA_SOLVER_MOCK_SOLVER: 'false',
      },
    },
  ],
};
