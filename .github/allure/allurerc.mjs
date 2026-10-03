export default {
  name: "Car Service Platform",
  output: "./allure-report",
  historyPath: "./allure-history/history.jsonl",
  historyLimit: 20,
  plugins: {
    awesome: {
      options: {
        reportName: "Car Service Platform test report",
        singleFile: false,
        reportLanguage: "en",
        groupBy: ["epic", "feature", "story"],
      },
    },
  },
};
