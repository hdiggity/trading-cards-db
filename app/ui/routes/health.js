const express = require('express');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const router = express.Router();

/**
 * GET /health
 * health check endpoint for monitoring and load balancers
 * returns 200 if all systems are healthy, 503 if any critical system is down
 */
router.get('/health', async (req, res) => {
  const health = {
    status: 'healthy',
    timestamp: new Date().toISOString(),
    uptime: process.uptime(),
    checks: {}
  };

  let allHealthy = true;

  // check 1: environment configuration
  try {
    if (!process.env.OPENAI_API_KEY) {
      health.checks.openai_config = {
        status: 'unhealthy',
        message: 'openai api key not configured'
      };
      allHealthy = false;
    } else {
      health.checks.openai_config = {
        status: 'healthy',
        message: 'openai api key configured'
      };
    }
  } catch (err) {
    health.checks.openai_config = {
      status: 'unhealthy',
      error: err.message
    };
    allHealthy = false;
  }

  // check 2: database file exists (for sqlite)
  try {
    const dbUrl = process.env.DATABASE_URL || 'sqlite:///cards/verified/trading_cards.db';

    if (dbUrl.startsWith('sqlite:')) {
      // extract file path from sqlite url
      const dbPath = dbUrl.replace('sqlite:///', '');
      const fullPath = path.resolve(dbPath);

      if (fs.existsSync(fullPath)) {
        const stats = fs.statSync(fullPath);
        health.checks.database = {
          status: 'healthy',
          type: 'sqlite',
          path: fullPath,
          size_mb: (stats.size / (1024 * 1024)).toFixed(2)
        };
      } else {
        health.checks.database = {
          status: 'warning',
          type: 'sqlite',
          message: 'database file does not exist yet (will be created on first use)',
          path: fullPath
        };
      }
    } else {
      health.checks.database = {
        status: 'healthy',
        type: 'postgresql',
        message: 'postgresql connection not tested in health check'
      };
    }
  } catch (err) {
    health.checks.database = {
      status: 'unhealthy',
      error: err.message
    };
    allHealthy = false;
  }

  // check 3: required directories
  try {
    const requiredDirs = [
      'cards',
      'cards/unprocessed_bulk_back',
      'cards/pending_verification',
      'cards/verified'
    ];

    const dirStatuses = {};
    for (const dir of requiredDirs) {
      const fullPath = path.resolve(dir);
      dirStatuses[dir] = fs.existsSync(fullPath) ? 'exists' : 'missing';
    }

    const allExist = Object.values(dirStatuses).every(status => status === 'exists');

    health.checks.directories = {
      status: allExist ? 'healthy' : 'warning',
      directories: dirStatuses
    };

    if (!allExist) {
      health.checks.directories.message = 'some directories missing (will be created as needed)';
    }
  } catch (err) {
    health.checks.directories = {
      status: 'unhealthy',
      error: err.message
    };
    allHealthy = false;
  }

  // check 4: python environment
  try {
    const pythonCheck = await new Promise((resolve) => {
      const timeout = setTimeout(() => {
        resolve({
          status: 'unhealthy',
          error: 'python check timeout'
        });
      }, 5000);

      const python = spawn('python', ['--version']);

      let version = '';
      python.stdout.on('data', (data) => {
        version += data.toString();
      });
      python.stderr.on('data', (data) => {
        version += data.toString();
      });

      python.on('close', (code) => {
        clearTimeout(timeout);
        if (code === 0) {
          resolve({
            status: 'healthy',
            version: version.trim()
          });
        } else {
          resolve({
            status: 'unhealthy',
            error: 'python not found or error occurred'
          });
        }
      });

      python.on('error', (err) => {
        clearTimeout(timeout);
        resolve({
          status: 'unhealthy',
          error: err.message
        });
      });
    });

    health.checks.python = pythonCheck;

    if (pythonCheck.status === 'unhealthy') {
      allHealthy = false;
    }
  } catch (err) {
    health.checks.python = {
      status: 'unhealthy',
      error: err.message
    };
    allHealthy = false;
  }

  // check 5: memory usage
  try {
    const memUsage = process.memoryUsage();
    const memUsageMB = {
      rss: (memUsage.rss / (1024 * 1024)).toFixed(2),
      heapTotal: (memUsage.heapTotal / (1024 * 1024)).toFixed(2),
      heapUsed: (memUsage.heapUsed / (1024 * 1024)).toFixed(2),
      external: (memUsage.external / (1024 * 1024)).toFixed(2)
    };

    health.checks.memory = {
      status: 'healthy',
      usage_mb: memUsageMB
    };
  } catch (err) {
    health.checks.memory = {
      status: 'unhealthy',
      error: err.message
    };
  }

  // set overall status
  if (!allHealthy) {
    health.status = 'unhealthy';
    return res.status(503).json(health);
  }

  res.status(200).json(health);
});

/**
 * GET /health/readiness
 * readiness check for kubernetes-style orchestration
 * returns 200 when service is ready to accept traffic
 */
router.get('/health/readiness', (req, res) => {
  // simple readiness check - can be expanded based on requirements
  const ready = {
    status: 'ready',
    timestamp: new Date().toISOString()
  };

  res.status(200).json(ready);
});

/**
 * GET /health/liveness
 * liveness check for kubernetes-style orchestration
 * returns 200 if process is alive (even if degraded)
 */
router.get('/health/liveness', (req, res) => {
  res.status(200).json({
    status: 'alive',
    timestamp: new Date().toISOString(),
    uptime: process.uptime()
  });
});

module.exports = router;
