/*
 * Coverage catalog for the local extension.
 *
 * geoId values are intentionally explicit.  Country ids below are the ids
 * already used by the extension.  State/territory ids are left empty until
 * they are copied from a real LinkedIn jobs URL; the queue never invents or
 * guesses a geoId.
 */
(function (root) {
  const occupations = [
    {id:'management-administration', name:'管理与行政', socMajor:'11', anzscoMajor:'1', keywords:['Manager','Operations Manager','Project Manager','Administrative Coordinator']},
    {id:'sales-marketing', name:'销售与市场', socMajor:'13', anzscoMajor:'2', keywords:['Sales Representative','Account Executive','Marketing Specialist','Business Development Manager']},
    {id:'software-it', name:'软件与 IT', socMajor:'15', anzscoMajor:'2', keywords:['Software Engineer','Developer','Systems Administrator','IT Support Specialist']},
    {id:'data-ai', name:'数据与人工智能', socMajor:'15', anzscoMajor:'2', keywords:['Data Analyst','Data Scientist','Data Engineer','Machine Learning Engineer']},
    {id:'engineering-manufacturing', name:'工程与制造', socMajor:'17', anzscoMajor:'3', keywords:['Mechanical Engineer','Electrical Engineer','Manufacturing Engineer','Process Engineer']},
    {id:'healthcare-nursing', name:'医疗与护理', socMajor:'29', anzscoMajor:'2', keywords:['Registered Nurse','Nurse Practitioner','Medical Assistant','Healthcare Administrator']},
    {id:'education-research', name:'教育与研究', socMajor:'25', anzscoMajor:'2', keywords:['Teacher','Lecturer','Research Assistant','Instructional Designer']},
    {id:'finance-accounting', name:'金融与会计', socMajor:'13', anzscoMajor:'2', keywords:['Accountant','Financial Analyst','Finance Manager','Bookkeeper']},
    {id:'legal-compliance', name:'法律与合规', socMajor:'23', anzscoMajor:'2', keywords:['Lawyer','Legal Counsel','Compliance Analyst','Paralegal']},
    {id:'human-resources', name:'人力资源', socMajor:'13', anzscoMajor:'2', keywords:['Human Resources Manager','Recruiter','HR Business Partner','Talent Acquisition Specialist']},
    {id:'customer-service', name:'客服与呼叫中心', socMajor:'43', anzscoMajor:'4', keywords:['Customer Service Representative','Call Center Representative','Customer Success Manager','Help Desk']},
    {id:'logistics-supply-chain', name:'物流与供应链', socMajor:'13', anzscoMajor:'1', keywords:['Supply Chain Analyst','Logistics Coordinator','Procurement Specialist','Warehouse Manager']},
    {id:'construction', name:'建筑与施工', socMajor:'47', anzscoMajor:'3', keywords:['Construction Manager','Project Superintendent','Estimator','Site Supervisor']},
    {id:'retail-hospitality', name:'零售与酒店', socMajor:'35', anzscoMajor:'4', keywords:['Retail Manager','Store Manager','Chef','Hotel Manager']},
    {id:'media-design', name:'媒体与设计', socMajor:'27', anzscoMajor:'2', keywords:['Graphic Designer','UX Designer','Content Writer','Video Producer']},
    {id:'government-public-service', name:'政府与公共服务', socMajor:'11', anzscoMajor:'1', keywords:['Policy Officer','Program Officer','Public Administration','Government Relations']},
    {id:'agriculture-resources', name:'农业与资源', socMajor:'45', anzscoMajor:'3', keywords:['Agronomist','Farm Manager','Mining Engineer','Environmental Officer']},
    {id:'trades-maintenance', name:'技工与维修', socMajor:'49', anzscoMajor:'3', keywords:['Electrician','Plumber','Maintenance Technician','Automotive Technician']},
    {id:'security', name:'安保', socMajor:'33', anzscoMajor:'4', keywords:['Security Officer','Security Manager','Loss Prevention Officer','Cybersecurity Analyst']},
    {id:'real-estate', name:'房地产', socMajor:'41', anzscoMajor:'2', keywords:['Real Estate Agent','Property Manager','Leasing Consultant','Facilities Manager']},
    {id:'science-laboratory', name:'科学与实验室', socMajor:'19', anzscoMajor:'2', keywords:['Laboratory Technician','Research Scientist','Chemist','Quality Control Analyst']},
    {id:'social-services', name:'社会服务', socMajor:'21', anzscoMajor:'4', keywords:['Social Worker','Case Manager','Counselor','Community Services Coordinator']},
    {id:'transportation', name:'交通运输', socMajor:'53', anzscoMajor:'4', keywords:['Truck Driver','Delivery Driver','Dispatcher','Transport Manager']},
    {id:'internship-graduate', name:'实习与毕业生岗位', socMajor:'', anzscoMajor:'', keywords:['Intern','Graduate','Entry Level','Apprentice']},
    {id:'other-general', name:'其他通用岗位', socMajor:'', anzscoMajor:'', keywords:['Coordinator','Specialist','Associate','Assistant']}
  ];

  const usNames = [
    ['AL','Alabama'],['AK','Alaska'],['AZ','Arizona'],['AR','Arkansas'],['CA','California'],['CO','Colorado'],['CT','Connecticut'],['DE','Delaware'],['DC','District of Columbia'],['FL','Florida'],['GA','Georgia'],['HI','Hawaii'],['ID','Idaho'],['IL','Illinois'],['IN','Indiana'],['IA','Iowa'],['KS','Kansas'],['KY','Kentucky'],['LA','Louisiana'],['ME','Maine'],['MD','Maryland'],['MA','Massachusetts'],['MI','Michigan'],['MN','Minnesota'],['MS','Mississippi'],['MO','Missouri'],['MT','Montana'],['NE','Nebraska'],['NV','Nevada'],['NH','New Hampshire'],['NJ','New Jersey'],['NM','New Mexico'],['NY','New York'],['NC','North Carolina'],['ND','North Dakota'],['OH','Ohio'],['OK','Oklahoma'],['OR','Oregon'],['PA','Pennsylvania'],['RI','Rhode Island'],['SC','South Carolina'],['SD','South Dakota'],['TN','Tennessee'],['TX','Texas'],['UT','Utah'],['VT','Vermont'],['VA','Virginia'],['WA','Washington'],['WV','West Virginia'],['WI','Wisconsin'],['WY','Wyoming']
  ];
  const auNames = [['NSW','New South Wales'],['VIC','Victoria'],['QLD','Queensland'],['WA','Western Australia'],['SA','South Australia'],['TAS','Tasmania'],['NT','Northern Territory'],['ACT','Australian Capital Territory']];
  const regions = (country, entries) => entries.map(([code, name]) => ({
    id: `${country.toLowerCase()}-${code.toLowerCase()}`,
    country, state: code, name, geoId: '', configured: false
  }));

  const countries = [
    {id:'us', country:'US', name:'United States', geoId:'103644278'},
    {id:'au', country:'AU', name:'Australia', geoId:'101452733'}
  ];

  const legacyLocations = {
    melbourne: {id:'au-vic-melbourne', name:'Melbourne', country:'AU', state:'VIC', geoId:'100992797'},
    sydney: {id:'au-nsw-sydney', name:'Sydney', country:'AU', state:'NSW', geoId:'104769905'},
    austin: {id:'us-tx-austin', name:'Austin', country:'US', state:'TX', geoId:'104472865'},
    australia: {id:'au', name:'Australia', country:'AU', geoId:'101452733'},
    usa: {id:'us', name:'United States', country:'US', geoId:'103644278'}
  };

  const catalog = {occupations, countries, regions: [...regions('US', usNames), ...regions('AU', auNames)], legacyLocations};
  if (typeof module !== 'undefined' && module.exports) module.exports = catalog;
  else root.LINKEDIN_CATALOG = catalog;
})(typeof globalThis !== 'undefined' ? globalThis : this);
