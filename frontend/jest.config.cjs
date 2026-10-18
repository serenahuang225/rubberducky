module.exports = {
  preset: 'jest-expo',
  testMatch: ['<rootDir>/src/**/*.test.ts?(x)'],
  maxWorkers: 1,
  watchman: false,
  setupFiles: ['<rootDir>/jest.setup.cjs'],
  // Jest follows the package "react-native" export, which is ESM. Tests load the CJS build.
  moduleNameMapper: {
    '^lucide-react-native$':
      '<rootDir>/node_modules/lucide-react-native/dist/cjs/lucide-react-native.js',
  },
};
